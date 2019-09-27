import os
import subprocess

import charmhelpers.core as ch_core

import charms_openstack.charm


OVS_ETCDIR = '/etc/openvswitch'


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
def ovn_key(cls):
    return os.path.join(OVS_ETCDIR, 'key_host')


@charms_openstack.adapters.config_property
def ovn_cert(cls):
    return os.path.join(OVS_ETCDIR, 'cert_host')


@charms_openstack.adapters.config_property
def ovn_ca_cert(cls):
    return os.path.join(OVS_ETCDIR,
                        '{}.crt'.format(cls.charm_instance.name))


class OVNControllerCharm(charms_openstack.charm.OpenStackCharm):
    release = 'stein'
    name = 'ovn-controller'
    packages = ['ovn-host']
    services = ['ovn-host']
    required_relations = ['certificates', 'ovsdb']
    restart_map = {
        '/etc/default/ovn-host': 'ovn-host',
    }
    python_version = 3

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
            with open(ovn_ca_cert(self.adapters_instance), 'w') as crt:
                crt.write(
                    tls_object['ca'] +
                    os.linesep +
                    tls_object.get('chain', ''))
            self.configure_cert(OVS_ETCDIR,
                                tls_object['cert'],
                                tls_object['key'],
                                cn='host')
            break

    def configure_ovs(self, ovsdb_interface):
            self.run('ovs-vsctl',
                     'set-ssl',
                     ovn_key(self.adapters_instance),
                     ovn_cert(self.adapters_instance),
                     ovn_ca_cert(self.adapters_instance))
            self.run('ovs-vsctl',
                     'set',
                     'open',
                     '.',
                     'external-ids:ovn-remote={}'
                     .format(','.join(ovsdb_interface.db_sb_connection_strs)))
            self.run('ovs-vsctl', 'set', 'open', '.',
                     'external-ids:ovn-encap-type=geneve')
            self.run('ovs-vsctl', 'set', 'open', '.',
                     'external-ids:ovn-encap-ip={}'
                     .format(cluster_local_addr(None)))
            self.restart_all()
