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


@charms_openstack.adapters.config_property
def cluster_local_addr(cls):
    """Address the ``ovsdb-server`` processes should be bound to.

    :param cls: charms_openstack.adapters.ConfigurationAdapter derived class
                instance.  Charm class instance is at cls.charm_instance.
    :type: cls: charms_openstack.adapters.ConfiguartionAdapter
    :returns: IP address selected for cluster communication on local unit.
    :rtype: str
    """
    # XXX this should probably be made space aware
    # for addr in cls.charm_instance.get_local_addresses():
    #     return addr
    return ch_core.hookenv.unit_get('private-address')


@charms_openstack.adapters.config_property
def db_nb_port(cls):
    """Port the ``ovsdb-server`` process for Northbound DB should listen to."""
    return DB_NB_PORT


@charms_openstack.adapters.config_property
def db_sb_port(cls):
    """Port the ``ovsdb-server`` process for Southbound DB should listen to."""
    return DB_SB_PORT


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

    def install(self):
        """Mask the ``ovn-central`` service before initial installation.

        This is done to prevent extraneous standalone DB initialization and
        subsequent upgrade to clustered DB when configuration is rendered.

        We need to manually create the symlink as the package is not installed
        yet and subsequently systemctl(1) has no knowledge of it.
        """
        ovn_central_service_file = '/etc/systemd/system/ovn-central.service'
        if not os.path.islink(ovn_central_service_file):
            os.symlink('/dev/null', ovn_central_service_file)
        super().install()

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

    def enable_services(self):
        """Enable services.

        :returns: True on success, False on failure.
        :rtype: bool"""
        if self.check_if_paused() != (None, None):
            return False
        for service in self.services:
            ch_core.host.service_resume(service)
        return True

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
            self.restart_all()
            break
