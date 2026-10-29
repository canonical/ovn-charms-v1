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
"""Client for the EPA orchestrator, which hands out the CPUs of a host.

The ``epa-orchestrator`` snap keeps track of which CPUs it has handed to
which service, so services sharing a host do not end up pinned to the same
CPUs.  It is installed by the ``epa-orchestrator`` subordinate charm and
answers requests on a Unix socket.
"""
import json
import os
import socket

EPA_SOCKET = '/var/snap/epa-orchestrator/current/data/epa.sock'
EPA_API_VERSION = '1.0'

# Seconds to wait on the daemon, which answers local requests at once, so a
# hook is not held by one that has stopped answering.
EPA_TIMEOUT = 10

# Ordinary CPUs balanced by the scheduler, and CPUs it leaves alone as
# taken from the ``isolcpus`` kernel parameter.
EPA_POOL_GENERAL = 'general'
EPA_POOL_ISOLATED = 'isolated'

# Only hand out CPUs no other service holds, and keep handing out the same
# ones on every request, rather than taking them back from other services.
EPA_POLICY_NON_PREEMPTIVE = 'non-preemptive'


class EPAError(Exception):
    """The EPA orchestrator could not satisfy a request."""


def is_available(socket_path=EPA_SOCKET):
    """Whether the EPA orchestrator is installed on this host.

    :param socket_path: Path to the EPA orchestrator socket.
    :type socket_path: str
    :rtype: bool
    """
    return os.path.exists(socket_path)


def request(payload, socket_path=EPA_SOCKET):
    """Send a request to the EPA orchestrator.

    :param payload: Request
    :type payload: Dict[str,any]
    :param socket_path: Path to the EPA orchestrator socket.
    :type socket_path: str
    :returns: Reply
    :rtype: Dict[str,any]
    :raises: EPAError
    """
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(EPA_TIMEOUT)
            sock.connect(socket_path)
            sock.sendall(json.dumps(payload).encode())
            # The daemon closes the connection once it has replied.
            reply = b''
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                reply += data
    except OSError as e:
        raise EPAError('Unable to talk to the EPA orchestrator on {}: {}'
                       .format(socket_path, e))
    try:
        reply = json.loads(reply)
    except ValueError as e:
        raise EPAError('Invalid reply from the EPA orchestrator to {}: {}'
                       .format(payload, e))
    if not isinstance(reply, dict):
        raise EPAError('Invalid reply from the EPA orchestrator to {}: {}'
                       .format(payload, reply))
    if reply.get('error'):
        raise EPAError('EPA orchestrator request {} failed: {}'
                       .format(payload, reply['error']))
    return reply


def allocate_numa_cores(service_name, numa_node, num_of_cores,
                        pool=EPA_POOL_GENERAL, socket_path=EPA_SOCKET):
    """Hold CPUs of a NUMA node for a service.

    :param service_name: Name the CPUs are held under.
    :type service_name: str
    :param numa_node: NUMA node to take the CPUs from.
    :type numa_node: int
    :param num_of_cores: Number of CPUs, or -1 to release the CPUs held on
                         the NUMA node.
    :type num_of_cores: int
    :param pool: CPU pool to take the CPUs from.
    :type pool: str
    :param socket_path: Path to the EPA orchestrator socket.
    :type socket_path: str
    :returns: CPU list of the CPUs held, for example ``8-11,72-75``.
    :rtype: str
    :raises: EPAError
    """
    if num_of_cores > 0:
        check_cpu_pools(socket_path=socket_path)
    reply = request({
        'version': EPA_API_VERSION,
        'action': 'allocate_numa_cores',
        'service_name': service_name,
        'numa_node': numa_node,
        'num_of_cores': num_of_cores,
        'pool': pool,
        'preemption_policy': EPA_POLICY_NON_PREEMPTIVE,
    }, socket_path=socket_path)
    try:
        return reply['cores_allocated']
    except KeyError:
        raise EPAError('No cores_allocated in the EPA orchestrator reply: {}'
                       .format(reply))


def check_cpu_pools(socket_path=EPA_SOCKET):
    """Make sure the EPA orchestrator honours pools and non-preemption.

    A daemon that predates them ignores the fields it does not know, and
    takes the CPUs it hands out away from the services holding them, so it
    has to be told apart before it is asked for any.

    :param socket_path: Path to the EPA orchestrator socket.
    :type socket_path: str
    :raises: EPAError
    """
    reply = request({
        'version': EPA_API_VERSION,
        'action': 'list_allocations',
    }, socket_path=socket_path)
    if not {'cpu-pools', 'non-preemptive-allocations'}.issubset(
            reply.get('supported_cpu_features', [])):
        raise EPAError('The EPA orchestrator does not support CPU pools '
                       'and non-preemptive allocations, refresh the '
                       'epa-orchestrator snap.')
