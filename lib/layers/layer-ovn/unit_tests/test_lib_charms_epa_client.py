# Copyright 2026 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import socket
import tempfile
import threading
import unittest

import unittest.mock as mock

import charms.epa_client as epa_client

# A reply FakeEPA never sends, keeping the connection open instead.
SILENT = object()


class FakeEPA(object):
    """Answer requests on a Unix socket the way the EPA daemon does."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []
        self._tmpdir = tempfile.TemporaryDirectory()
        self.socket_path = os.path.join(self._tmpdir.name, 'epa.sock')
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(self.socket_path)
        self._server.listen(1)
        self._server.settimeout(5)
        self._thread = threading.Thread(target=self._serve)
        self._thread.start()

    def _serve(self):
        for reply in self.replies:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            with conn:
                self.requests.append(json.loads(conn.recv(1024)))
                if reply is SILENT:
                    # Until the client gives up.
                    conn.recv(1024)
                elif isinstance(reply, bytes):
                    conn.sendall(reply)
                else:
                    conn.sendall(json.dumps(reply).encode())

    def close(self):
        self._server.close()
        self._thread.join(timeout=10)
        self._tmpdir.cleanup()


# What ``list_allocations`` answers with on a daemon with and without
# support for CPU pools and non-preemptive allocations.
LIST_ALLOCATIONS = {
    'version': '1.0',
    'supported_cpu_features': ['non-preemptive-allocations', 'cpu-pools'],
    'pool': 'isolated',
    'total_allocations': 0,
    'total_allocated_cpus': 0,
    'total_available_cpus': 0,
    'remaining_available_cpus': 0,
    'allocations': [],
}
LIST_ALLOCATIONS_LEGACY = {
    'version': '1.0',
    'total_allocations': 0,
    'total_allocated_cpus': 0,
    'total_available_cpus': 0,
    'remaining_available_cpus': 0,
    'allocations': [],
}


class TestEPAClient(unittest.TestCase):

    def fake_epa(self, *replies):
        epa = FakeEPA(*replies)
        self.addCleanup(epa.close)
        return epa

    def test_is_available(self):
        epa = self.fake_epa()
        self.assertTrue(epa_client.is_available(epa.socket_path))
        self.assertFalse(epa_client.is_available(epa.socket_path + '.gone'))

    def test_allocate_numa_cores(self):
        epa = self.fake_epa(LIST_ALLOCATIONS, {
            'version': '1.0',
            'service_name': 'ovs-vswitchd',
            'pool': 'general',
            'preemption_policy': 'non-preemptive',
            'numa_node': 1,
            'num_of_cores': 8,
            'cores_allocated': '136-139,392-395',
            'total_available_cpus': 64,
            'remaining_available_cpus': 56,
        })
        self.assertEqual(
            epa_client.allocate_numa_cores(
                'ovs-vswitchd', 1, 8, socket_path=epa.socket_path),
            '136-139,392-395')
        self.assertEqual(epa.requests, [
            {'version': '1.0', 'action': 'list_allocations'},
            {
                'version': '1.0',
                'action': 'allocate_numa_cores',
                'service_name': 'ovs-vswitchd',
                'numa_node': 1,
                'num_of_cores': 8,
                'pool': 'general',
                'preemption_policy': 'non-preemptive',
            },
        ])

    def test_allocate_numa_cores_isolated(self):
        # PMD threads poll in a busy loop and want CPUs the scheduler
        # leaves alone.
        epa = self.fake_epa(LIST_ALLOCATIONS, {
            'version': '1.0',
            'service_name': 'ovs-vswitchd-pmd',
            'pool': 'isolated',
            'preemption_policy': 'non-preemptive',
            'numa_node': 1,
            'num_of_cores': 4,
            'cores_allocated': '64-67',
            'total_available_cpus': 32,
            'remaining_available_cpus': 28,
        })
        self.assertEqual(
            epa_client.allocate_numa_cores(
                'ovs-vswitchd-pmd', 1, 4, pool='isolated',
                socket_path=epa.socket_path),
            '64-67')
        self.assertEqual(epa.requests[1]['pool'], 'isolated')

    def test_allocate_numa_cores_error(self):
        epa = self.fake_epa(LIST_ALLOCATIONS, {
            'version': '1.0',
            'error': 'NUMA node 1 only has 3 eligible CPUs, but 8 were '
                     'requested',
        })
        with self.assertRaisesRegex(epa_client.EPAError, 'only has 3'):
            epa_client.allocate_numa_cores(
                'ovs-vswitchd', 1, 8, socket_path=epa.socket_path)

    def test_allocate_numa_cores_without_pools(self):
        # A daemon that predates CPU pools ignores the fields it does not
        # know, and takes the CPUs it hands out away from the services
        # holding them, so it must not be asked at all.
        epa = self.fake_epa(LIST_ALLOCATIONS_LEGACY)
        with self.assertRaisesRegex(epa_client.EPAError, 'CPU pools'):
            epa_client.allocate_numa_cores(
                'ovs-vswitchd', 1, 8, socket_path=epa.socket_path)
        self.assertEqual(epa.requests, [
            {'version': '1.0', 'action': 'list_allocations'}])

    def test_release_numa_cores(self):
        # Releasing takes nothing from anyone, so any daemon may be asked.
        epa = self.fake_epa({
            'version': '1.0',
            'service_name': 'ovs-vswitchd',
            'numa_node': 0,
            'num_of_cores': -1,
            'cores_allocated': '',
            'total_available_cpus': 64,
            'remaining_available_cpus': 64,
        })
        self.assertEqual(
            epa_client.allocate_numa_cores(
                'ovs-vswitchd', 0, -1, socket_path=epa.socket_path),
            '')
        self.assertEqual([r['action'] for r in epa.requests],
                         ['allocate_numa_cores'])

    def test_silent_daemon(self):
        # A daemon that accepts and never answers must not hold the hook.
        epa = self.fake_epa(SILENT)
        with mock.patch.object(epa_client, 'EPA_TIMEOUT', 0.2):
            with self.assertRaisesRegex(epa_client.EPAError, 'talk to'):
                epa_client.request({'action': 'list_allocations'},
                                   socket_path=epa.socket_path)

    def test_broken_replies(self):
        # Whatever the daemon answers, the caller only has EPAError to
        # handle.
        for reply in (b'', b'{"version": "1.0", "cores_', b'[]'):
            epa = self.fake_epa(reply)
            with self.assertRaisesRegex(epa_client.EPAError, 'reply'):
                epa_client.request({'action': 'list_allocations'},
                                   socket_path=epa.socket_path)

    def test_allocate_numa_cores_missing_field(self):
        epa = self.fake_epa(LIST_ALLOCATIONS, {'version': '1.0'})
        with self.assertRaisesRegex(epa_client.EPAError, 'cores_allocated'):
            epa_client.allocate_numa_cores(
                'ovs-vswitchd', 1, 8, socket_path=epa.socket_path)
