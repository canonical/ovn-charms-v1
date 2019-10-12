import collections
import os
import subprocess

import charmhelpers.core as ch_core

import charms_openstack.adapters
import charms_openstack.charm


OVS_ETCDIR = '/etc/openvswitch'


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


class NeutronPluginRelationAdapter(
        charms_openstack.adapters.OpenStackRelationAdapter):

    @property
    def metadata_shared_secret(self):
        return self.relation.get_or_create_shared_secret()


class OVNChassisCharmRelationAdapters(
        charms_openstack.adapters.OpenStackRelationAdapters):
    relation_adapters = {
        'nova_compute': NeutronPluginRelationAdapter,
    }


class OVNChassisCharm(charms_openstack.charm.OpenStackCharm):
    # OpenvSwitch and OVN is distributed as part of the Ubuntu Cloud Archive
    # Pockets get their name from OpenStack releases
    release = 'train'
    package_codenames = {
        'ovn-host': collections.OrderedDict([
            ('2.12', 'train'),
        ]),
    }
    name = 'ovn-chassis'
    packages = ['ovn-host']
    services = ['ovn-host']
    adapters_class = OVNChassisCharmRelationAdapters
    required_relations = ['certificates', 'ovsdb']
    restart_map = {
        '/etc/default/ovn-host': ['ovn-host'],
    }
    python_version = 3
    # Name of unitdata key with information on whether to enable metadata
    metadata_kv_key = 'ovn-chassis-enable-metadata'

    def __init__(self, **kwargs):
        enable_metadata = ch_core.unitdata.kv().get(
            self.metadata_kv_key, False)
        print(enable_metadata)
        if enable_metadata:
            # XXX for Train onwards, we should use the
            #     ``networking-ovn-metadata-agent`` package
            metadata_agent = 'networking-ovn-metadata-agent'
            self.packages.extend(['python3-networking-ovn', 'haproxy'])
            self.services.append(metadata_agent)
            self.restart_map.update({
                '/etc/neutron/'
                'networking_ovn_metadata_agent.ini': [metadata_agent],
                '/etc/init.d/''networking-ovn-metadata-agent': [
                    metadata_agent],
                '/lib/systemd/system/networking-ovn-metadata-agent.service': (
                    [metadata_agent]),
            })
            self.permission_override_map = {
                '/etc/init.d/networking-ovn-metadata-agent': 0o755,
            }
        super().__init__(**kwargs)

    def disable_metadata(self):
        db = ch_core.unitdata.kv()
        db.unset(self.metadata_kv_key)
        db.flush()

    def enable_metadata(self):
        db = ch_core.unitdata.kv()
        db.set(self.metadata_kv_key, True)
        db.flush()

    def run(self, *args):
        cp = subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True,
            universal_newlines=True)
        ch_core.hookenv.log(cp, level=ch_core.hookenv.INFO)

    def configure_tls(self, certificates_interface=None):
        """Override default handler prepare certs per OVNs taste."""
        # The default handler in ``OpenStackCharm`` class does the CA only
        tls_objects = self.get_certs_and_keys(
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
                     .format(ovsdb_interface.cluster_local_addr))
            self.restart_all()
