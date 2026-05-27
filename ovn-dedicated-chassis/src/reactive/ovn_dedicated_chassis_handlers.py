import charms.reactive as reactive

from . import ovn_chassis_charm_handlers
import charms_openstack.charm as charm


# NOTE: code shared among the chassis charms can be found in the 'ovn' layer.
@reactive.when_not(ovn_chassis_charm_handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG)
def enable_ovn_chassis_handlers():
    reactive.set_flag(
        ovn_chassis_charm_handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG)


@reactive.when_not('is-update-status-hook')
def configure_deferred_restarts():
    with charm.provide_charm_instance() as instance:
        instance.configure_deferred_restarts()
