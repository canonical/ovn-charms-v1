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
import collections
import ipaddress
import json
import jsonschema
import os
import re
import subprocess

import charms.reactive as reactive

import charmhelpers.core as ch_core
import charmhelpers.contrib.charmsupport.nrpe as nrpe
import charmhelpers.contrib.openstack.context as os_context
import charmhelpers.contrib.network.ovs as ch_ovs
import charmhelpers.contrib.network.ovs.ovsdb as ch_ovsdb
import charmhelpers.contrib.openstack.deferred_events as deferred_events
import charmhelpers.fetch as ch_fetch

import charms_openstack.adapters
import charms_openstack.charm

from charms.layer import snap


CERT_RELATION = 'certificates'
_DEFERABLE_SVC_LIST = ['openvswitch-switch', 'ovn-controller', 'ovn-host',
                       'ovs-vswitchd', 'ovsdb-server', 'ovs-record-hostname']


def is_deferred_event_permitted(config_rendered, enable_auto_restarts_changed,
                                check_deferred_events, is_restart_permitted):
    """Check whether a deferred event can run or not.

    :param config_rendered: true if config.rendered flag is set. When this
                            flag is not set, deferred events are permitted
                            to allow completing first installation.
    :type config_rendered: bool
    :param enable_auto_restarts_changed: true if enable_auto_restarts
                                         changed since last iteration.
                                         If enable-auto-restarts has
                                         changed, deferred events will be
                                         permitted irrespective of what it
                                         was changed to. This ensures that
                                         this method is not immediately
                                         deferred when enable-auto-restarts
                                         is initially set to False.
    :type enable_auto_restarts_changed: bool
    :param check_deferred_events: Whether to check if restarts are
                                  permitted before running hook.
    :type check_deferred_events: bool
    :param is_restart_permitted: if true deferred events can run.
    :type is_restart_permitted: bool
    """

    if ((not config_rendered) or (not check_deferred_events) or
            enable_auto_restarts_changed or is_restart_permitted):
        return True
    return False


class DeferredEventMixin():
    """Mixin to add to charm class to add support for deferred events."""

    def restart_on_change(self):
        """Restart the services in the self.restart_map{} attribute if any of
        the files identified by the keys changes for the wrapped call.

        Usage:

           with restart_on_change(restart_map, ...):
               do_stuff_that_might_trigger_a_restart()
               ...
        """
        return ch_core.host.restart_on_change(
            self.full_restart_map,
            stopstart=True,
            restart_functions=getattr(self, 'restart_functions', None),
            can_restart_now_f=deferred_events.check_and_record_restart_request,
            post_svc_restart_f=deferred_events.process_svc_restart)

    @property
    def deferable_services(self):
        """Services which should be stopped from restarting.

        All services from self.services are deferable. But the charm may
        install a package which install a service that the charm does not add
        to its restart_map. In that case it will be missing from
        self.services. However one of the jobs of deferred events is to ensure
        that packages updates outside of charms also do not restart services.
        To ensure there is a complete list take the services from self.services
        and also add in a known list of networking services.

        NOTE: It does not matter if one of the services in the list is not
        installed on the system.

        """
        svcs = self.services[:]
        svcs.extend(_DEFERABLE_SVC_LIST)
        return list(set(svcs))

    def configure_deferred_restarts(self):
        """Install deferred event files and policies.

        Check that the charm supports deferred events by checking for the
        presence of the 'enable-auto-restarts' config option. If it is present
        then install the supporting files and directories, however,
        configure_deferred_restarts only enables deferred events if
        'enable-auto-restarts' is True.
        """
        if 'enable-auto-restarts' in ch_core.hookenv.config().keys():
            deferred_events.configure_deferred_restarts(
                self.deferable_services)
            # Reactive charms execute perm missing.
            os.chmod(
                '/var/lib/charm/{}/policy-rc.d'.format(
                    ch_core.hookenv.service_name()),
                0o755)

    def custom_assess_status_check(self):
        """Report deferred events in charm status message."""
        state = None
        message = None
        deferred_events.check_restart_timestamps()
        events = collections.defaultdict(set)
        for e in deferred_events.get_deferred_events():
            events[e.action].add(e.service)
        for action, svcs in events.items():
            svc_msg = "Services queued for {}: {}".format(
                action, ', '.join(sorted(svcs)))
            state = 'active'
            if message:
                message = "{}. {}".format(message, svc_msg)
            else:
                message = svc_msg
        deferred_hooks = deferred_events.get_deferred_hooks()
        if deferred_hooks:
            state = 'active'
            svc_msg = "Hooks skipped due to disabled auto restarts: {}".format(
                ', '.join(sorted(deferred_hooks)))
            if message:
                message = "{}. {}".format(message, svc_msg)
            else:
                message = svc_msg
        return state, message

    def configure_ovs(self, sb_conn, mlockall_changed,
                      check_deferred_events=True):
        """Run configure_ovs if permitted.

        :param sb_conn: Comma separated string of OVSDB connection methods.
        :type sb_conn: str
        :param mlockall_changed: Whether the mlockall param has changed.
        :type mlockall_changed: bool
        :param check_deferred_events: Whether to check if restarts are
                                      permitted before running hook.
        :type check_deferred_events: bool
        """
        config_rendered = reactive.flags.is_flag_set('config.rendered')
        changed = reactive.flags.is_flag_set(
            'config.changed.enable-auto-restarts'
        )
        is_restart_permitted = deferred_events.is_restart_permitted()
        if is_deferred_event_permitted(config_rendered, changed,
                                       check_deferred_events,
                                       is_restart_permitted):
            deferred_events.clear_deferred_hook('configure_ovs')
            super().configure_ovs(sb_conn, mlockall_changed)
        else:
            deferred_events.set_deferred_hook('configure_ovs')

    def install(self, check_deferred_events=True):
        """Run install if permitted.

        :param check_deferred_events: Whether to check if restarts are
                                      permitted before running hook.
        :type check_deferred_events: bool
        """
        config_rendered = reactive.flags.is_flag_set('config.rendered')
        changed = reactive.flags.is_flag_set(
            'config.changed.enable-auto-restarts'
        )
        is_restart_permitted = deferred_events.is_restart_permitted()
        if is_deferred_event_permitted(config_rendered, changed,
                                       check_deferred_events,
                                       is_restart_permitted):
            deferred_events.clear_deferred_hook('install')
            super().install()
        else:
            deferred_events.set_deferred_hook('install')


class OVNConfigurationAdapter(
        charms_openstack.adapters.ConfigurationAdapter):
    """Provide a configuration adapter for OVN."""

    class OSContextObjectView(object):

        def __init__(self, ctxt):
            """Initialize OSContextObjectView instance.

            :param ctxt: Dictionary with context variables
            :type ctxt: Dict[str,any]
            """
            self.__dict__ = ctxt

    def __init__(self, **kwargs):
        """Initialize contexts consumed from charm helpers."""
        super().__init__(**kwargs)
        self._dpdk_device = None
        self._sriov_device = None
        self._disable_mlockall = None
        self._validation_errors = {}
        if ch_core.hookenv.config('enable-dpdk'):
            self._dpdk_device = self.OSContextObjectView(
                os_context.DPDKDeviceContext(
                    bridges_key=self.charm_instance.bridges_key)())
            self._ovs_dpdk_cpu_overlap_check()
        if (ch_core.hookenv.config('enable-hardware-offload') or
                ch_core.hookenv.config('enable-sriov')):
            self._sriov_device = os_context.SRIOVContext()
        self._bridge_interface_map = None
        self._card_serial_number = None

    @property
    def validation_errors(self):
        return self._validation_errors

    @property
    def ovn_key(self):
        return os.path.join(self.charm_instance.ovn_sysconfdir(), 'key_host')

    @property
    def ovn_cert(self):
        return os.path.join(self.charm_instance.ovn_sysconfdir(), 'cert_host')

    @property
    def ovn_ca_cert(self):
        return os.path.join(self.charm_instance.ovn_sysconfdir(),
                            '{}.crt'.format(self.charm_instance.name))

    @property
    def dpdk_device(self):
        return self._dpdk_device

    @property
    def chassis_name(self):
        return self.charm_instance.get_ovs_hostname()

    @property
    def sriov_device(self):
        return self._sriov_device

    @property
    def mlockall_disabled(self):
        """Determine if Open vSwitch use of mlockall() should be disabled

        If the disable-mlockall config option is unset, mlockall will be
        disabled if running in a container and will default to enabled if
        not running in a container.
        """
        self._disable_mlockall = ch_core.hookenv.config('disable-mlockall')
        if self._disable_mlockall is None:
            self._disable_mlockall = False
            if ch_core.host.is_container():
                self._disable_mlockall = True
        return self._disable_mlockall

    @property
    def bridge_interface_map(self):
        if not self._bridge_interface_map:
            try:
                self._bridge_interface_map = os_context.BridgePortInterfaceMap(
                    bridges_key=self.charm_instance.bridges_key)
                return self._bridge_interface_map
            except ValueError:
                self._validation_errors[self.charm_instance.bridges_key] = (
                    'Wrong format for bridge-interface-mappings. '
                    'Expected format is space-delimited list of '
                    'key-value pairs. Ex: "br-internet:00:00:5e:00:00:42 '
                    'br-provider:enp3s0f0"')
                return None

    @property
    def card_serial_number(self):
        """Determine the NIC card serial number based on charm config"""
        # Empty spec.
        if not self.vpd_device_spec:
            return None

        if self._card_serial_number:
            return self._card_serial_number
        try:
            spec = json.loads(self.vpd_device_spec)
        except json.JSONDecodeError:
            self._validation_errors['vpd-device-spec'] = (
                'Invalid JSON provided for VPD device spec:'
                f' {self.vpd_device_spec}')
            return None

        schema = {
            'type': 'array',
            'items': {'type': 'object',
                      'properties': {
                          'bus': {
                              'type': 'string',
                              'pattern': '^pci$'},
                          'vendor_id': {
                              'type': 'string',
                              'pattern': '^([\\da-fA-F]{4})$'},
                          'device_id': {
                              'type': 'string',
                              'pattern': '^([\\da-fA-F]{4})$'}},
                      'required': [
                          'bus',
                          'vendor_id',
                          'device_id']}
        }
        try:
            jsonschema.validate(spec, schema)
        except jsonschema.ValidationError:
            self._validation_errors['vpd-device-spec'] = (
                'Invalid VPD device spec does not match the schema: '
                f'{self.vpd_device_spec}')
            return None

        # There can be one or multiple specs specified. We iterate over those
        # assuming that one charm may be deployed on machines with different
        # hardware present. The order of the items in the spec list shows the
        # precedence an operator wishes to use in case devices matching
        # multiple specs are present on one host. However, considering DPUs
        # will mainly be the target machines here, one device per machine is
        # a likely case.
        specs = json.loads(self.vpd_device_spec)
        for spec in specs:
            vendor_id = spec['vendor_id']
            device_id = spec['device_id']
            out = subprocess.check_output(['lspci', '-d',
                                           f'{vendor_id}:{device_id}', '-vv'],
                                          text=True)
            # If a device is not present the output will be empty.
            if not out:
                continue

            serials = re.findall(r'\[SN\] Serial number: (?P<serial>\S+)',
                                 str(out), re.MULTILINE)
            if serials:
                # Assume we only have one chip per card for now since all DPUs
                # we have seen so far are like this - just take the first
                # occurrence of a serial number for now even if there are
                # multiple devices representing ports exposed by one chip.
                return serials[0]
            # If a serial number isn't exposed on a matching device, we try
            # other specs just in case by iterating further.
        # Tried all the specs - but haven't found a serial number.
        return None

    def _ovs_dpdk_cpu_overlap_check(self):
        """Check for overlap between dpdk-lcore-mask and pmd-cpu-mask."""
        dpdk_context = os_context.OVSDPDKDeviceContext(
            bridges_key=self.charm_instance.bridges_key)
        if not (int(dpdk_context.pmd_cpu_mask(), 16) &
                int(dpdk_context.cpu_mask(), 16)):
            return

        ch_core.hookenv.log('Overlap detected between dpdk-lcore-mask '
                            'and pmd-cpu-mask.',
                            level=ch_core.hookenv.WARNING)
        self._validation_errors['pmd-cpu-mask'] = (
            'Fix overlap between dpdk-lcore-mask and pmd-cpu-mask.')

    @property
    def _ovn_source(self):
        if (not self.ovn_source
                and reactive.is_flag_set('leadership.set.install_stamp')
                and ch_core.host.lsb_release()['DISTRIB_CODENAME'] == 'focal'):
            return 'cloud:focal-ovn-22.03'
        return self.ovn_source

    @property
    def ovs_exporter_snap_channel(self):
        """Validate a provided snap channel and return it

        Any prefix is ignored ('0.10' in '0.10/stable' for example). If
        a config value is empty it means that the snap does not need to
        be installed.
        """
        channel = self.ovs_exporter_channel
        if not channel:
            return None

        channel_suffix = channel.split('/')[-1]
        if channel_suffix not in ('stable', 'candidate', 'beta', 'edge'):
            return 'stable'
        return channel_suffix


class NeutronPluginRelationAdapter(
        charms_openstack.adapters.OpenStackRelationAdapter):
    """Relation adapter for neutron-plugin interface."""

    @property
    def metadata_shared_secret(self):
        return self.relation.get_or_create_shared_secret()


class OVNChassisCharmRelationAdapters(
        charms_openstack.adapters.OpenStackRelationAdapters):
    """Provide dictionary of relation adapters for use by OVN Chassis charms.
    """
    relation_adapters = {
        # Note that RabbitMQ is only used for the Neutron SRIOV agent
        'amqp': charms_openstack.adapters.RabbitMQRelationAdapter,
        'nova_compute': NeutronPluginRelationAdapter,
    }


class BaseOVNChassisCharm(charms_openstack.charm.OpenStackCharm):
    """Base class for the OVN Chassis charms."""
    abstract_class = True
    # Note that we currently do not support pivoting between release specific
    # charm classes in the OVN charms.  We still need this set to ensure the
    # default methods are happy.
    #
    # Also see docstring in the `upgrade_if_available` method.
    package_codenames = {
        'ovn-host': collections.OrderedDict([
            ('20', 'ussuri'),
            ('22', 'yoga'),
        ]),
    }
    nova_vhost_user_file = '/etc/tmpfiles.d/nova-ovs-vhost-user.conf'
    release_pkg = 'ovn-host'
    adapters_class = OVNChassisCharmRelationAdapters
    configuration_class = OVNConfigurationAdapter
    required_relations = [CERT_RELATION, 'ovsdb']
    python_version = 3
    bridges_key = 'bridge-interface-mappings'
    # Extra packages and services to be installed, managed and monitored if
    # charm forms part of an Openstack Deployment
    openstack_packages = ['neutron-ovn-metadata-agent']
    openstack_services = ['neutron-ovn-metadata-agent']
    openstack_restart_map = {
        '/etc/neutron/neutron_ovn_metadata_agent.ini': [
            'neutron-ovn-metadata-agent']}
    # Services to be monitored by nrpe
    nrpe_check_base_services = [
        'ovn-controller',
        'ovs-vswitchd',
        'ovsdb-server']
    nrpe_check_openstack_services = [
        'neutron-ovn-metadata-agent']
    # ovs-exporter service name
    exporter_service = 'snap.prometheus-ovs-exporter.ovs-exporter'

    @property
    def nrpe_check_services(self):
        """Full list of services to be monitored by nrpe.

        :returns: List of services
        :rtype: List[str]
        """
        _check_services = self.nrpe_check_base_services[:]
        if self.enable_openstack:
            _check_services.extend(self.nrpe_check_openstack_services)
        return _check_services

    @property
    def enable_openstack(self):
        """Whether charm forms part of an OpenStack deployment.

        :returns: Whether charm forms part of an OpenStack deployment
        :rtype: boolean
        """
        return reactive.is_flag_set('charm.ovn-chassis.enable-openstack')

    @property
    def additional_dpdk_libraries(self):
        """A list of additional runtime libraries to be installed for dpdk.

        :returns: list of additional packages to install
        :rtype: List[str]
        """
        packages = []
        if self.options.enable_dpdk and self.options.dpdk_runtime_libraries:
            # dpdk_runtime_libraries is a space delimited list of strings.
            # some options are disabled by passing 'None' so filter out a
            # specifying of a 'None' value
            pkgs = list(filter(lambda x: x and x.lower() != 'none',
                               self.options.dpdk_runtime_libraries.split()))
            # Attempt to be nice and resolve the package names the user has
            # provided in order to allow for users to specify 'hinic' etc for
            # packages. To do this, we will search for all packages using the
            # format of `librte-*<name>* and return all matching packages.
            for name in pkgs:
                regex = re.compile(r'(^\S.*)', re.MULTILINE)
                if name.lower().startswith('librte'):
                    packages.append(name)
                    continue

                cp = self.run('apt-cache', 'policy',
                              'librte-*{}*'.format(name))
                # The apt-cache search does not return an error code if the
                # package could not be found and the return code is 0. The
                # stdout will be empty in this case and the regex won't
                # produce a match. Log a warning message and use the provided
                # package name anyways. This may cause a failure to install,
                # but the user should have an idea of why.
                results = re.findall(regex, cp.stdout)
                if not results:
                    ch_core.hookenv.log(('Unable to find candidate librte '
                                         'package for {}. Using raw name '
                                         'provided.').format(name),
                                        ch_core.hookenv.WARN)
                    packages.append(name)
                    continue

                # The regex doesn't remove the trailing ':' so strip it out
                # before adding it to the list of packages
                packages.extend([p[:-1] for p in results])

        return packages

    @property
    def packages(self):
        """Full list of packages to be installed.

        :returns: List of packages
        :rtype: List[str]
        """
        _packages = ['ovn-host']
        if self.options.enable_dpdk:
            _packages.extend(['openvswitch-switch-dpdk'])
            _packages.extend(self.additional_dpdk_libraries)
        if self.enable_openstack:
            if self.options.enable_sriov:
                _packages.append('neutron-sriov-agent')
            _packages.extend(self.openstack_packages)
        return _packages

    @property
    def purge_packages(self):
        """Packages to purge.

        This is a property instead of a class variable because we need to
        determine the list of packages to purge at runtime.

        :returns: List of packages to purge
        :rtype: List[str]
        """
        _purge_packages = ['mlnx-switchdev-mode', 'sriov-netplan-shim']
        if not self.options.enable_dpdk:
            _purge_packages.extend(['openvswitch-switch-dpdk'])
        return _purge_packages

    @property
    def group(self):
        """Group that should own files

        :returns: Group name
        :rtype: str
        """
        # When OpenStack support is enabled the various config files laid
        # out for Neutron agents need to have group ownership of 'neutron'
        # for the services to have access to them.
        if self.enable_openstack:
            return 'neutron'
        else:
            return 'root'

    @property
    def services(self):
        """Full list of services to be managed.

        :returns: List of services.
        :rtype: List[str]
        """
        _services = ['ovn-host']
        if self.enable_openstack:
            _services.extend(self.openstack_services)
        return _services

    @property
    def restart_map(self):
        """Which services should be notified when a file changes.

        :returns: Restart map
        :rtype: Dict[str, List[str]]
        """
        # Note that we use the standard config render features of
        # charms.openstack to just copy this file in place hence no
        # service attached.
        # The charm will configure the system-id at runtime in the
        # ``configure_ovs`` method.  The openvswitch-switch init script will
        # use the on-disk file on service restart.
        _restart_map = {
            '/etc/openvswitch/system-id.conf': [],
            '/etc/default/openvswitch-switch': [],
            # Netplan config snippets will be rendered when SR-IOV or Hardware
            # Offload is enabled.  However we always want to render the file
            # to ensure configuration is removed when any of those features
            # are disabled.
            '/etc/netplan/150-charm-ovn.yaml': [],
        }
        # The ``dpdk`` system init script takes care of binding devices
        # to the driver specified in configuration at run- and boot- time.
        #
        # NOTE: we must take care to perform device lookup and store
        # mapping information in the system before binding the interfaces
        # as important information such as hardware ethernet address (MAC)
        # will be harder to get at once bound. (The device disappears from
        # sysfs)
        if self.options.enable_dpdk:
            _restart_map.update({
                '/etc/dpdk/interfaces': ['dpdk']})
        if self.enable_openstack:
            _restart_map.update(self.openstack_restart_map)
            if self.options.enable_sriov:
                _restart_map.update({
                    '/etc/neutron/neutron.conf': ['neutron-sriov-agent'],
                    '/etc/neutron/plugins/ml2/sriov_agent.ini': [
                        'neutron-sriov-agent'],
                })
            elif self.options.enable_dpdk:
                # Note that we use the standard config render features of
                # charms.openstack to just copy this file in place hence no
                # service attached. systemd-tmpfiles-setup will take care of
                # it at boot and we will do a first-time initialization in the
                # ``install`` method.
                _restart_map.update({self.nova_vhost_user_file: []})
        return _restart_map

    def __init__(self, **kwargs):
        """Allow augmenting behaviour on external factors."""
        super().__init__(**kwargs)
        if (self.enable_openstack and self.options.enable_sriov
                and 'amqp' not in self.required_relations):
            self.required_relations.append('amqp')

    def configure_ovn_source(self):
        """Configure the OVN overlay archive."""
        if self.options.ovn_source:
            # The end user has added configuration which may require full
            # processing including key extraction.
            self.configure_source(config_key='ovn-source')
        elif self.options._ovn_source:
            # The end user has not added configuration and we want to use the
            # runtime determined default value.
            #
            # We cannot use the default `configure_source` method here as it
            # attempts to access charm config directly.
            ch_fetch.add_source(self.options._ovn_source)
            ch_fetch.apt_update(fatal=True)

    def configure_sources(self):
        """Configure package sources for OVN charms.

        The principal charms provide both a `source` and a `ovn-source`
        configuration option, and the subordinate charms only provide the
        `ovn-source` configuration option.

        The `source` configuration option is tied into the charms.openstack
        `source_config_key` class variable and is inteded to be used with a
        full UCA archive.  The default methods and functions will apply special
        meaning to the name used for further processing, and as such the
        `source` configuration option is not suitable for use with an overlay
        archive.

        The `ovn-source` configuration option is intended to be used with a
        slim overlay archive containing only OVN and its dependencies.

        The two configuration options can be used simultaneously, and the
        underlying charm-helpers code will write the configuration out into
        separate files depending on the value of the options.

        Ref: https://github.com/juju/charm-helpers/commit/982319b136b
        """
        self.configure_ovn_source()
        if self.source_config_key:
            self.configure_source()

    def install(self):
        """Extend the default install method."""
        self.configure_sources()
        super().install()

        if (not reactive.is_flag_set('charm.installed') and
                self.options.mlockall_disabled):
            # We need to render /etc/default/openvswitch-switch after the
            # initial install and restart openvswitch-switch. This is done to
            # ensure that when the disable-mlockall config option is unset,
            # mlockall is disabled when running in a container.
            # The ovn-host stop/start is needed until the following bug is
            # fixed: https://pad.lv/1913736. Really this is a work-around
            # to get the pause/resume test to work.
            self.render_configs(['/etc/default/openvswitch-switch'])
            ch_core.host.service_stop('ovn-host')
            ch_core.host.service_restart('openvswitch-switch')
            ch_core.host.service_start('ovn-host')

        if self.options.enable_dpdk:
            self.run('update-alternatives', '--set', 'ovs-vswitchd',
                     '/usr/lib/openvswitch-switch-dpdk/ovs-vswitchd-dpdk')
            # Do first-time initialization of the directory used for vhostuser
            # sockets.  Neutron is made aware of this path centrally by the
            # neutron-api-plugin-ovn charm.
            #
            # Neutron will make per chassis decisions based on chassis
            # configuration whether vif_type will be 'ovs' or 'vhostuser'.
            #
            # This allows having a mix of DPDK and non-DPDK nodes in the same
            # deployment.
            if self.enable_openstack and not os.path.exists(
                    '/run/libvirt-vhost-user'):
                self.render_configs([self.nova_vhost_user_file])
                self.run('systemd-tmpfiles', '--create')
        else:
            self.run('update-alternatives', '--set', 'ovs-vswitchd',
                     '/usr/lib/openvswitch-switch/ovs-vswitchd')
            if (reactive.is_flag_set('config.changed.enable-dpdk') and
                    self.remove_obsolete_packages()):
                ch_core.host.service_restart('openvswitch-switch')

    def upgrade_charm(self):
        """Remove the now deprecated networking tools PPA if present."""
        super().upgrade_charm()

        # Remove this now unused charm maintained configuration file
        try:
            os.remove('/etc/sriov-netplan-shim/interfaces.yaml')
        except FileNotFoundError:
            pass

        # Remove PPA
        try:
            os.remove('/etc/apt/sources.list.d/'
                      'openstack-charmers-ubuntu-networking-tools-focal.list')
            ch_fetch.apt_update(fatal=True)
        except FileNotFoundError:
            pass

        # Ensure that `config.changed.ovn-source` flag is not set on charm
        # upgrade.  When upgrading from an older charm, this flag will be
        # set even though the config has not changed.
        reactive.clear_flag('config.changed.ovn-source')

    def ovn_upgrade_available(self, package=None, snap=None):
        """Determine whether an OVN upgrade is available.

        Make use of the installed package version and the package version
        available in the apt cache to determine availability of new version.
        """
        self.configure_sources()
        cur_vers = self.get_package_version(self.release_pkg,
                                            apt_cache_sufficient=False)
        avail_vers = self.get_package_version(self.release_pkg,
                                              apt_cache_sufficient=True)
        ch_fetch.apt_pkg.init()
        return ch_fetch.apt_pkg.version_compare(avail_vers, cur_vers) == 1

    def upgrade_if_available(self, interfaces_list):
        """Upgrade OVN if an upgrade is available.

        At present there is no need to pivot to a release specific charm class
        when upgrading OVN.  As such we override the default method to keep
        this simpler, given OVN versions are not fully represented in the
        OpenStack version machinery that the default method relies on.

        :param interfaces_list: List of instances of interface classes
        :returns: None
        """
        if self.ovn_upgrade_available(self.release_pkg):
            self.do_openstack_pkg_upgrade(upgrade_openstack=False)
            self.render_with_interfaces(interfaces_list)

    def resume(self):
        """Do full hook execution on resume.

        A part of the migration strategy to OVN is to start the chassis charms
        paused only to resume them as soon as cleanup after the previous SDN
        has been completed.

        For this to work we need to run a full hook execution on resume to make
        sure the system is configured properly.
        """
        super().resume()

        ch_core.hookenv.log("Re-execing as full hook execution after resume.",
                            level=ch_core.hookenv.INFO)
        os.execl(
            '/usr/bin/env',
            'python3',
            os.path.join(ch_core.hookenv.charm_dir(), 'hooks/config-changed'),
        )

    def custom_assess_status_last_check(self):
        """Check if config validation errors are present and block if they are.

        Returns (None, None) if the config is ok, or a status, message if the
        config is invalid.

        :returns status & message info
        :rtype: (status, message) or (None, None)
        """

        if self.options.validation_errors:
            status_msg = ', '.join([
                f'{k}: "{msg}"' for k, msg
                in self.options.validation_errors.items()
            ])
            return 'blocked', status_msg

        if (self.options.enable_dpdk and
                self.options._ovs_dpdk_cpu_overlap_check()):
            ch_core.hookenv.log('Overlap detected between dpdk-lcore-mask '
                                'and pmd-cpu-mask.',
                                level=ch_core.hookenv.WARNING)
            message = 'Fix overlap between dpdk-lcore-mask and pmd-cpu-mask.'
            return 'blocked', message

        return None, None

    def states_to_check(self, required_relations=None):
        """Override parent method to add custom messaging.

        Note that this method will only override the messaging for certain
        relations, any relations we don't know about will get the default
        treatment from the parent method.

        :param required_relations: Override `required_relations` class instance
                                   variable.
        :type required_relations: Optional[List[str]]
        :returns: Map of relation name to flags to check presence of
                  accompanied by status and message.
        :rtype: collections.OrderedDict[str, List[Tuple[str, str, str]]]
        """
        # Retrieve default state map
        states_to_check = super().states_to_check(
            required_relations=required_relations)

        # The parent method will always return a OrderedDict
        if CERT_RELATION in states_to_check:
            # for the certificates relation we want to replace all messaging
            states_to_check[CERT_RELATION] = [
                # the certificates relation has no connected state
                ('{}.available'.format(CERT_RELATION),
                 'blocked',
                 "'{}' missing".format(CERT_RELATION)),
                # we cannot proceed until Vault have provided server
                # certificates
                ('{}.server.certs.available'.format(CERT_RELATION),
                 'waiting',
                 "'{}' awaiting server certificate data"
                 .format(CERT_RELATION)),
            ]

        return states_to_check

    @staticmethod
    def ovn_sysconfdir():
        """Provide path to OVN system configuration."""
        return '/etc/ovn'

    def run(self, *args):
        """Run external process and return result.

        :param *args: Command name and arguments.
        :type *args: str
        :returns: Data about completed process
        :rtype: subprocess.CompletedProcess
        :raises: subprocess.CalledProcessError
        """
        cp = subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True,
            universal_newlines=True)
        ch_core.hookenv.log(cp, level=ch_core.hookenv.INFO)
        return cp

    def get_certificate_requests(self):
        """Override default certificate request handler.

        We make use of OVN RBAC for authorization of writes from chassis nodes
        to the Southbound DB. The OVSDB server implementation makes use of the
        CN in the certificate to grant access to individual chassis. The
        chassis name and CN must match for this to work.
        """
        return {self.get_ovs_hostname(): {'sans': []}}

    def configure_tls(self, certificates_interface=None):
        """Override default handler prepare certs per OVNs taste.

        :param certificates_interface: A certificates relation
        :type certificates_interface: Optional[TlsRequires(reactive.Endpoint)]
        """
        # The default handler in ``OpenStackCharm`` class does the CA only
        tls_objects = self.get_certs_and_keys(
            certificates_interface=certificates_interface)
        if not tls_objects:
            # We have no configuration settings ssl_* nor a certificates
            # relation to vault.
            # Avoid LP Bug#1900457
            ch_core.hookenv.log(
                'No TLS objects available yet. Deferring TLS processing',
                level=ch_core.hookenv.DEBUG)
            return

        expected_cn = self.get_ovs_hostname()

        for tls_object in tls_objects:
            if tls_object.get('cn') != expected_cn:
                continue
            with open(self.options.ovn_ca_cert, 'w') as crt:
                chain = tls_object.get('chain')
                if chain:
                    crt.write(tls_object['ca'] + os.linesep + chain)
                else:
                    crt.write(tls_object['ca'])

            self.configure_cert(self.ovn_sysconfdir(),
                                tls_object['cert'],
                                tls_object['key'],
                                cn='host')
            reactive.set_flag('ovn.certs.changed')
            break
        else:
            ch_core.hookenv.log('No certificate with CN matching hostname '
                                'configured in OVS: "{}"'
                                .format(expected_cn),
                                level=ch_core.hookenv.INFO)
            # Flag that we are not satisfied with the provided certificates
            reactive.clear_flag('certificates.available')

    @staticmethod
    def _format_addr(addr):
        """Validate and format IP address

        :param addr: IPv6 or IPv4 address
        :type addr: str
        :returns: Address string, optionally encapsulated in brackets ([])
        :rtype: str
        :raises: ValueError
        """
        ipaddr = ipaddress.ip_address(addr)
        if isinstance(ipaddr, ipaddress.IPv6Address):
            fmt = '[{}]'
        else:
            fmt = '{}'
        return fmt.format(ipaddr)

    def get_data_ip(self):
        """Get IP of interface bound to ``data`` binding.

        :returns: IP address
        :rtype: str
        """
        # juju will always return address information, regardless of actual
        # presence of space binding.
        #
        # Unpack ourself as ``network_get_primary_address`` is deprecated
        return self._format_addr(
            ch_core.hookenv.network_get(
                'data')['bind-addresses'][0]['addresses'][0]['address'])

    @staticmethod
    def get_ovs_hostname():
        """Get hostname (FQDN) from Open vSwitch.

        :returns: Hostname as configured in Open vSwitch
        :rtype: str
        :raises: KeyError
        """
        # The Open vSwitch ``ovs-ctl`` script has already done the dirty work
        # of retrieving the hosts FQDN, use it.
        #
        # In the unlikely event of the hostname not being set in the database
        # we want to error out as this will cause malfunction.
        for row in ch_ovsdb.SimpleOVSDB('ovs-vsctl').open_vswitch:
            return row['external_ids']['hostname']

    def dpdk_eal_allow_devices(self, devices):
        """Build EAL command line argument for allowed devices.

        :param devices: PCI devices for use by DPDK
        :type devices: collections.OrderedDict[str,Tuple[str,str]]
        :returns: Command line arguments for use with DPDK EAL.
        :rtype: str
        """
        if ch_core.host.cmp_pkgrevno('dpdk', '20.11.3') >= 0:
            flag = '-a'
        else:
            # The allow argument changed at DPDK 20.11
            # https://github.com/DPDK/dpdk/commit/db27370b57202632ad8830352c1c0ee2dde4542f
            flag = '-w'

        return ' '.join([
            flag + ' ' + device
            for device in devices
        ])

    def configure_ovs_dpdk(self):
        """Configure DPDK specific bits in Open vSwitch.

        :returns: Whether something changed
        :rtype: bool
        """
        something_changed = False
        dpdk_context = os_context.OVSDPDKDeviceContext(
            bridges_key=self.bridges_key)
        opvs = ch_ovsdb.SimpleOVSDB('ovs-vsctl').open_vswitch
        other_config_fmt = 'other_config:{}'
        kv_pairs = (
            ('dpdk-lcore-mask',
             dpdk_context.cpu_mask()
             if self.options.enable_dpdk else None),
            ('dpdk-socket-mem',
             dpdk_context.socket_memory()
             if self.options.enable_dpdk else None),
            ('dpdk-init',
             'true'
             if self.options.enable_dpdk else None),
            ('dpdk-extra',
             self.dpdk_eal_allow_devices(dpdk_context.devices())
             if self.options.enable_dpdk else None),
            ('pmd-cpu-mask',
             dpdk_context.pmd_cpu_mask()
             if self.options.enable_dpdk and self.options.pmd_cpu_set
             else None),
        )
        for row in opvs:
            for k, v in (kv_pairs):
                other_config = row.get('other_config', {})
                if other_config.get(k) != v:
                    something_changed = True
                    if v:
                        opvs.set('.', other_config_fmt.format(k), v)
                    elif k in other_config:
                        opvs.remove('.', 'other_config', k)
                    else:
                        # NOT REACHED
                        pass
        return something_changed

    def configure_ovs_hw_offload(self):
        """Configure hardware offload specific bits in Open vSwitch.

        :returns: Whether something changed
        :rtype: bool
        """
        something_changed = False
        opvs = ch_ovsdb.SimpleOVSDB('ovs-vsctl').open_vswitch
        other_config_fmt = 'other_config:{}'
        kv_pairs = (
            ('hw-offload',
             'true'
             if self.options.enable_hardware_offload else None),
            ('max-idle',
             '30000'
             if self.options.enable_hardware_offload else None),
        )
        for row in opvs:
            for k, v in (kv_pairs):
                other_config = row.get('other_config', {})
                if other_config.get(k) != v:
                    something_changed = True
                    if v:
                        opvs.set('.', other_config_fmt.format(k), v)
                    elif k in other_config:
                        opvs.remove('.', 'other_config', k)
                    else:
                        # NOT REACHED
                        pass
        return something_changed

    def configure_ovs(self, sb_conn, mlockall_changed):
        """Global Open vSwitch configuration tasks.

        :param sb_conn: Comma separated string of OVSDB connection methods.
        :type sb_conn: str

        Note that running this method will restart the ``openvswitch-switch``
        service if required.
        """
        if self.check_if_paused() != (None, None):
            ch_core.hookenv.log('Unit is paused, defer global Open vSwitch '
                                'configuration tasks.',
                                level=ch_core.hookenv.INFO)
            return

        if mlockall_changed:
            # NOTE(fnordahl): We need to act immediately to changes to
            # OVS_DEFAULT in-line. It is important to write config to disk
            # and perhaps restart the openvswitch-swith service prior to
            # attempting to do run-time configuration of OVS as we may have
            # to pass options to `ovs-vsctl` for `ovs-vswitchd` to run at all.
            ch_core.host.service_restart('openvswitch-switch')
        else:
            # Must make sure the service runs otherwise calls to ``ovs-vsctl``
            # will hang.
            ch_core.host.service_start('openvswitch-switch')

        restart_required = False
        # NOTE(fnordahl): Due to what is probably a bug in Open vSwitch
        # subsequent calls to ``ovs-vsctl set-ssl`` will hang indefinitely
        # Work around this by passing ``--no-wait``.
        self.run('ovs-vsctl',
                 '--no-wait',
                 'set-ssl',
                 self.options.ovn_key,
                 self.options.ovn_cert,
                 self.options.ovn_ca_cert)

        if sb_conn:
            # The local ``ovn-controller`` process will retrieve information
            # about how to connect to OVN from the local Open vSwitch
            # database.
            cmd = ('ovs-vsctl',)
            for ovs_ext_id in ('external-ids:ovn-encap-type=geneve',
                               'external-ids:ovn-encap-ip={}'
                               .format(self.get_data_ip()),
                               'external-ids:system-id={}'
                               .format(self.get_ovs_hostname()),
                               'external-ids:ovn-remote={}'.format(sb_conn),
                               'external_ids:ovn-match-northd-version={}'
                               .format(self.options.enable_version_pinning),
                               'external-ids:ovn-monitor-all={}'
                               .format(self.options.ovn_monitor_all),
                               ):
                cmd = cmd + ('--', 'set', 'open-vswitch', '.', ovs_ext_id)
            self.run(*cmd)
        else:
            ch_core.hookenv.log('could not configure ovs due to unavailable '
                                'sbdb connection info - ovn-central relation '
                                'no longer available?',
                                level=ch_core.hookenv.WARNING)

        if self.enable_openstack:
            # OpenStack Nova expects the local OVSDB server to listen to
            # TCP port 6640 on localhost.  We use this for the OVN metadata
            # agent too, as it allows us to run it as a non-root user.
            # LP: #1852200
            target = 'ptcp:6640:127.0.0.1'
            for el in ch_ovsdb.SimpleOVSDB(
                    'ovs-vsctl').manager.find('target="{}"'.format(target)):
                break
            else:
                self.run('ovs-vsctl', '--id', '@manager',
                         'create', 'Manager', 'target="{}"'.format(target),
                         '--', 'add', 'Open_vSwitch', '.', 'manager_options',
                         '@manager')

        restart_required = (
            self.configure_ovs_hw_offload() | self.configure_ovs_dpdk())
        if restart_required:
            ch_core.host.service_restart('openvswitch-switch')

    def _get_port_type(self, port):
        """Determine port type from its interface records.

        :param port: Port record
        :type port: Dict[str,any]
        :returns: Port type as identified by its interface records.
        :rtype: str
        :raises: RuntimeError if interfaces are of different type.
        """
        if_records = port['interfaces']
        # SimpleOVSDB does not know the schema and does not represent list type
        # columns as lists when there is a single value.
        if not isinstance(if_records, list):
            if_records = [if_records]
        interfaces = ch_ovsdb.SimpleOVSDB('ovs-vsctl').interface
        if_types = [interfaces[if_record]['type']
                    for if_record in if_records]
        if not all(if_type == if_types[0] for if_type in if_types):
            raise RuntimeError('Port {} has interfaces of different types '
                               '({}), unable to determine port type.'
                               .format(port['_uuid'], if_types))
        return if_types[0]

    def _should_linkdown(self, port):
        """Determine whether we should request linkdown on port delete.

        :param port: Port record
        :type port: Dict[str,any]
        :returns: True or False
        :rtype: bool
        """
        # When a system is transitioning from kernel interfaces to DPDK, the
        # following will happen:
        # 1) System is configured to associate interfaces with the DPDK driver.
        # 2) The `dpdk` systemd service will be restarted which unbinds
        #    interfaces from the kernel driver.
        # 3) configure_bridges is called which will remove the interfaces that
        #    used to be associated with the kernel driver.
        #
        # At this point in time the interface name referred to in the Open
        # vSwitch configuration no longer exist in the system and as such
        # we should not attempt to modify the link state with `ip link`.
        #
        #
        # Moving in the other direction from DPDK to kernel drivers:
        # 1) System is configured to no longer associate interfaces with the
        #    DPDK driver.
        # 2) The functional test will reboot the test instance.
        # 3) configure_bridges is called which will remove the interfaces that
        #    used to be associated with the DPDK driver.
        #
        # The dpdk interface does not exist in the system and the charm
        # configuration says that DPDK is disabled.
        if self.options.enable_dpdk or self._get_port_type(port) == 'dpdk':
            return False
        return True

    def configure_bridges(self):
        """Configure Open vSwitch bridges ports and interfaces."""
        if self.check_if_paused() != (None, None):
            ch_core.hookenv.log('Unit is paused, defer Open vSwitch bridge '
                                'port interface configuration tasks.',
                                level=ch_core.hookenv.INFO)
            return

        bim = self.options.bridge_interface_map
        # A bridge interface mapping may be empty if an empty string is
        # specified, however, this is different from an invalid mapping in
        # which case the property returns None and we should not proceed.
        if bim is None:
            return

        bond_config = os_context.BondConfig()
        ch_core.hookenv.log('BridgePortInterfaceMap: "{}"'.format(bim.items()),
                            level=ch_core.hookenv.DEBUG)

        # build map of bridges to ovn networks with existing if-mapping on host
        # and at the same time build ovn-bridge-mappings string
        ovn_br_map_str = ''
        ovnbridges = collections.defaultdict(list)
        config_obm = self.config['ovn-bridge-mappings'] or ''
        for pair in sorted(config_obm.split()):
            network, bridge = pair.split(':', 1)
            if bridge in bim:
                ovnbridges[bridge].append(network)
                if ovn_br_map_str:
                    ovn_br_map_str += ','
                ovn_br_map_str += '{}:{}'.format(network, bridge)

        bridges = ch_ovsdb.SimpleOVSDB('ovs-vsctl').bridge
        ports = ch_ovsdb.SimpleOVSDB('ovs-vsctl').port
        for bridge in bridges.find('external_ids:charm-ovn-chassis=managed'):
            # remove bridges and ports that are managed by us and no longer in
            # config
            if bridge['name'] not in bim and bridge['name'] != 'br-int':
                ch_core.hookenv.log('removing bridge "{}" as it is no longer'
                                    'present in configuration for this unit.'
                                    .format(bridge['name']),
                                    level=ch_core.hookenv.DEBUG)
                ch_ovs.del_bridge(bridge['name'])
            else:
                for port in ports.find('external_ids:charm-ovn-chassis={}'
                                       .format(bridge['name'])):
                    if port['name'] not in bim[bridge['name']]:
                        ch_core.hookenv.log('removing port "{}" from bridge '
                                            '"{}" as it is no longer present '
                                            'in configuration for this unit.'
                                            .format(port['name'],
                                                    bridge['name']),
                                            level=ch_core.hookenv.DEBUG)
                        ch_ovs.del_bridge_port(
                            bridge['name'],
                            port['name'],
                            linkdown=self._should_linkdown(port))
        brdata = {
            'external-ids': {'charm-ovn-chassis': 'managed'},
            'protocols': 'OpenFlow13,OpenFlow15',
        }
        if self.options.enable_dpdk:
            brdata.update({'datapath-type': 'netdev'})
        else:
            brdata.update({'datapath-type': 'system'})
        # we always update the integration bridge to make sure it has settings
        # apropriate for the current charm configuration
        ch_ovs.add_bridge('br-int', brdata={
            **brdata,
            **{
                # for the integration bridge we want the datapath to await
                # controller action before adding any flows. This is to avoid
                # switching packets between isolated logical networks before
                # `ovn-controller` starts up.
                'fail-mode': 'secure',
                # Suppress in-band control flows for the integration bridge,
                # refer to ovn-architecture(7) for more details.
                'other-config': {'disable-in-band': 'true'},
            },
        })
        for br in bim:
            if br not in ovnbridges:
                continue
            ch_ovs.add_bridge(br, brdata={
                **brdata,
                # for bridges used for external connectivity we want the
                # datapath to act like an ordinary MAC-learning switch.
                **{'fail-mode': 'standalone'},
            })
            for port in bim[br]:
                ifdatamap = bim.get_ifdatamap(br, port)
                ifdatamap = {
                    port: {
                        **ifdata,
                        **{'external-ids': {'charm-ovn-chassis': br}},
                    }
                    for port, ifdata in ifdatamap.items()
                }

                if len(ifdatamap) > 1:
                    ch_ovs.add_bridge_bond(br, port, list(ifdatamap.keys()),
                                           bond_config.get_ovs_portdata(port),
                                           ifdatamap)
                else:
                    ch_ovs.add_bridge_port(br, port,
                                           ifdata=ifdatamap.get(port, {}),
                                           linkup=not self.options.enable_dpdk,
                                           promisc=None,
                                           portdata={
                                               'external-ids': {
                                                   'charm-ovn-chassis': br}})

        opvs = ch_ovsdb.SimpleOVSDB('ovs-vsctl').open_vswitch
        if ovn_br_map_str:
            opvs.set('.', 'external_ids:ovn-bridge-mappings', ovn_br_map_str)
        else:
            opvs.remove('.', 'external_ids', 'ovn-bridge-mappings')

        cms_opts = self._get_ovn_cms_options()
        if cms_opts:
            opvs.set('.', 'external_ids:ovn-cms-options', ','.join(cms_opts))
        else:
            opvs.remove('.', 'external_ids', 'ovn-cms-options')

    def _get_ovn_cms_options(self):
        """Get options to be passed into ovn-cms-options"""
        cms_opts = []
        if self.options.prefer_chassis_as_gw:
            cms_opts.append('enable-chassis-as-gw')
        if self.options.card_serial_number:
            cms_opts.append(
                f'card-serial-number={self.options.card_serial_number}')
        return cms_opts

    def render_nrpe(self):
        """Configure Nagios NRPE checks."""
        ch_core.hookenv.log("Rendering NRPE checks.",
                            level=ch_core.hookenv.INFO)
        hostname = nrpe.get_nagios_hostname()
        current_unit = nrpe.get_nagios_unit_name()
        # Determine if this is a subordinate unit or not
        if ch_core.hookenv.principal_unit() == ch_core.hookenv.local_unit():
            primary = True
        else:
            primary = False
        charm_nrpe = nrpe.NRPE(hostname=hostname, primary=primary)
        nrpe.add_init_service_checks(
            charm_nrpe, self.nrpe_check_services, current_unit)
        charm_nrpe.write()

    def configure_iptables_rules(self):
        """
        Configure `iptables` NOTRACK rules for GENEVE traffic in nf_conntrack

        The GENEVE/VXLAN traffic has randomized source ports[1], which
        plays badly with nf_conntrack in a busy cloud environment. Having
        randomized source ports change the five-tuple info, resulting to an
        increase in unique connections that nf_conntrack tracks. That
        inevitably leads to a full nf_conntrack table and connections to be
        dropped.

        NOTRACK rules allow nf_conntrack to ignore the said traffic. UDP
        flows with destination port 6081 will not be tracked by nf_conntrack
        while rules are in effect.

        [1]:(https://datatracker.ietf.org/doc/html/rfc8926#section-3.3)
        """
        ch_core.hookenv.log("Configuring iptables rules",
                            level=ch_core.hookenv.INFO)

        def append_notrack_rule(chain_name):
            """
            Append a iptables NOTRACK rule to a chain in raw table.

            :param str chain_name: Chain to append
            """
            args = ['iptables', '-t', 'raw', '-C', chain_name, '-p', 'udp',
                    '--dport', '6081', '-j', 'NOTRACK']
            try:
                self.run(*args)
                ch_core.hookenv.log(
                    "Rule `{}` append to `{}` chain skipped (already exists)"
                    .format(' '.join(args), chain_name),
                    level=ch_core.hookenv.INFO)
            except subprocess.CalledProcessError as cpe:
                if cpe.returncode != 1:
                    raise

                # Append command is exactly the same with check
                # except the check (-C) is replaced with append
                # (-A)
                args[3] = '-A'
                self.run(*args)
                ch_core.hookenv.log(
                    "Rule `{}` appended to `{}` chain"
                    .format(' '.join(args), chain_name),
                    level=ch_core.hookenv.INFO)

        append_notrack_rule('PREROUTING')
        append_notrack_rule('OUTPUT')

    def assess_exporter(self):
        is_installed = snap.is_installed('prometheus-ovs-exporter')
        channel = None
        channel = self.options.ovs_exporter_snap_channel
        if channel is None:
            if is_installed:
                snap.remove('prometheus-ovs-exporter')
            return

        if is_installed:
            snap.refresh('prometheus-ovs-exporter', channel=channel)
        else:
            snap.install('prometheus-ovs-exporter', channel=channel)
        snap.connect_all()

    def restart_exporter(self, only_inactive=False):
        """Restart OVS prometheus exporter service.

        :param only_inactive: If set to True, and the service is already
                              active, it wont' be restarted.
        :type only_inactive: bool
        :returns: None
        """
        needs_restart = (not only_inactive or
                         not ch_core.host.service_running(
                             self.exporter_service)
                         )

        if needs_restart:
            ch_core.hookenv.log(
                "Restarting OVS exporter", level=ch_core.hookenv.INFO)
            ch_core.host.service_restart(self.exporter_service)
        else:
            ch_core.hookenv.log(
                "Not restarting OVS exporter. Service is already active.",
                level=ch_core.hookenv.INFO)
