import charmhelpers.core as ch_core

import charms.reactive as reactive

import charms_openstack.bus
import charms_openstack.charm as charm


charms_openstack.bus.discover()

# Use the charms.openstack defaults for common states and hooks
charm.use_defaults(
    'charm.installed',
    'config.changed',
    'update-status',
    'upgrade-charm',
    'certificates.available',
)


@reactive.when_not('nova-compute.connected')
def disable_metadata():
    with charm.provide_charm_instance() as charm_instance:
        charm_instance.disable_metadata()
        charm_instance.assess_status()


@reactive.when('nova-compute.connected')
def enable_metadata():
    nova_compute = reactive.endpoint_from_flag('nova-compute.connected')
    nova_compute.publish_shared_secret()
    with charm.provide_charm_instance() as charm_instance:
        ch_core.hookenv.log(
            'DEBUG: {} {} {} {}'
            .format(charm_instance,
                    charm_instance.packages,
                    charm_instance.services,
                    charm_instance.restart_map),
            level=ch_core.hookenv.INFO)
        charm_instance.enable_metadata()
    with charm.provide_charm_instance() as charm_instance:
        ch_core.hookenv.log(
            'DEBUG: {} {} {} {}'
            .format(charm_instance,
                    charm_instance.packages,
                    charm_instance.services,
                    charm_instance.restart_map),
            level=ch_core.hookenv.INFO)
        charm_instance.install()
        charm_instance.assess_status()


@reactive.when('charm.installed')
@reactive.when_any('config.changed.ovn-bridge-mappings',
                   'config.changed.interface-bridge-mappings',
                   'run-default-upgrade-charm')
def configure_bridges():
    with charm.provide_charm_instance() as charm_instance:
        charm_instance.configure_bridges()
        reactive.clear_flag('config.changed.ovn-bridge-mappings')
        reactive.clear_flag('config.changed.interface-bridge-mappings')
        charm_instance.assess_status()


@reactive.when('ovsdb.available')
def configure_ovs():
    ovsdb = reactive.endpoint_from_flag('ovsdb.available')
    with charm.provide_charm_instance() as charm_instance:
        ch_core.hookenv.log(
            'DEBUG: {} {} {} {}'
            .format(charm_instance,
                    charm_instance.packages,
                    charm_instance.services,
                    charm_instance.restart_map),
            level=ch_core.hookenv.INFO)
        charm_instance.render_with_interfaces(
            charm.optional_interfaces((ovsdb,),
                                      'nova-compute.connected'))
        charm_instance.configure_ovs(ovsdb)
        charm_instance.assess_status()
