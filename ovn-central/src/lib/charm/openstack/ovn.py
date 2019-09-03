# Copyright 2019 Canonical Ltd
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

import os
import subprocess

import charmhelpers.core as ch_core

import charms_openstack.adapters
import charms_openstack.charm


OVS_ETCDIR = '/etc/openvswitch'
DB_NB_PORT = 6641
DB_SB_PORT = 6642


class OVNCharm(charms_openstack.charm.OpenStackCharm):
    release = 'queens'
    name = 'ovn'
    packages = ['ovn-central']
    services = ['ovn-central']
    required_relations = ['certificates']
    restart_map = {
        '/etc/default/ovn-central': services,
    }
    python_version = 3

    def _default_port_list(self, *_):
        """Return list of ports the payload listens too.

        The api_ports class attribute can not be used as it does not allow
        one service to listen to multiple ports.
        """
        return [DB_NB_PORT, DB_SB_PORT]

    def ports_to_check(self, *_):
        """Return list of ports to check the payload listens too.

        The api_ports class attribute can not be used as it does not allow
        one service to listen to multiple ports.
        """
        return self._default_port_list()

    @property
    def ovs_controller_cert(self):
        return os.path.join(OVS_ETCDIR, 'cert_host')

    @property
    def ovs_controller_key(self):
        return os.path.join(OVS_ETCDIR, 'key_host')

    def run(self, *args):
        cp = subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True,
            universal_newlines=True)
        ch_core.hookenv.log(cp, level=ch_core.hookenv.INFO)

    def configure_tls(self, certificates_interface=None):
        """Override default handler prepare certs per OVNs taste."""
        # The default handler in ``OpenStackCharm`` class does the CA only
        tls_objects = super().configure_tls(
            certificates_interface=certificates_interface)

        for tls_object in tls_objects:
            self.configure_cert(OVS_ETCDIR,
                                tls_object['cert'],
                                tls_object['key'],
                                cn='host')
            for ctl in 'ovs-vsctl', 'ovn-nbctl', 'ovn-sbctl':
                self.run(ctl,
                         'set-ssl',
                         self.ovs_controller_key,
                         self.ovs_controller_cert,
                         '/usr/local/share/ca-certificates/{}.crt'
                         .format(self.service_name))
            self.run('ovn-nbctl',
                     'set-connection',
                     'pssl:{}'.format(DB_NB_PORT))
            self.run('ovn-sbctl',
                     'set-connection',
                     'role=ovn-controller',
                     'pssl:{}'.format(DB_SB_PORT))
            self.run('ovs-vsctl',
                     'set',
                     'open',
                     '.',
                     'external-ids:ovn-remote=ssl:127.0.0.1:{}'
                     .format(DB_SB_PORT))
