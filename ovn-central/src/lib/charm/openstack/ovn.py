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

import charmhelpers.core as ch_core
import charmhelpers.contrib.openstack.cert_utils as cert_utils

import charms_openstack.charm


OVS_ETCDIR = '/etc/openvswitch'
OVS_CERTDIR = os.path.join(OVS_ETCDIR, 'tls')


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

    def configure_tls(self, certificates_interface=None):
        """Override default handler prepare certs per OVNs taste."""
        # The default handler in ``OpenStackCharm`` class does the CA only
        tls_objects = super().configure_tls(
            certificates_interface=certificates_interface)

        ch_core.hookenv.log('configure_tls: "{}"'.format(tls_objects))
        for tls_object in tls_objects:
            self.configure_cert(OVS_CERTDIR,
                                tls_object['cert'],
                                tls_object['key'],
                                cn=tls_object['cn'])
            cert_utils.create_ip_cert_links(OVS_CERTDIR)
