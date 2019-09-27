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


@reactive.when('ovsdb.available')
def configure_ovs():
    ovsdb = reactive.endpoint_from_flag('ovsdb.available')
    with charm.provide_charm_instance() as charm_instance:
        charm_instance.render_with_interfaces([ovsdb])
        charm_instance.configure_ovs(ovsdb)
        charm_instance.assess_status()
