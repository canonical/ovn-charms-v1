# Overview

This charm provides the Open Virtual Network (OVN) local controller, Open
vSwitch Database and Switch.

On successful deployment the unit will be enlisted as a `Chassis` in the OVN
network.

Open vSwitch bridges for integration, external Layer2 and Layer3 connectivity
is managed by the charm.

# Usage

OVN makes use of Public Key Infrastructure (PKI) to authenticate and authorize
control plane communication.  The charm requires a Certificate Authority to be
present in the model as represented by the `certificates` relation.

The [OpenStack Base bundle][openstack-base-bundle] gives an example of how you
can deploy OpenStack and OVN with [Vault][charm-vault] to automate certificate
lifecycle management.

Please refer to the [OVN Appendix][ovn-cdg] in the
[OpenStack Charms Deployment Guide][cdg] for details.

## Network Spaces support

This charm supports the use of Juju Network Spaces.

By binding the `ovsdb` endpoint you can influence which interface will be used
for communication with the OVN Southbound DB as well as overlay traffic.

    juju deploy ovn-dedicated-chassis --bind "ovsdb=internal-space"

By binding the `data` extra-binding you can influence which interface will be
used for overlay traffic.

    juju deploy ovn-dedicated-chassis --bind "data=overlay-space"

## Port Configuration

Chassis port configuration is composed of a mapping between physical network
names to bridge names (`ovn-bridge-mappings`) and individual interface to
bridge names (`bridge-interface-mappings`).  There must be a match in both
configuration options before the charm will configure bridge and interfaces on
a unit.

The physical network name can be referenced when the administrator programs the
OVN logical flows, either by talking directly to the Northbound database, or by
interfaceing with a Cloud Management System (CMS).

Networks for use with external Layer3 connectivity should have mappings on
chassis located in the vicinity of the datacenter border gateways.  Having two
or more chassis with mappings for a Layer3 network will have OVN automatically
configure highly available routers with liveness detection provided by the
Bidirectional Forwarding Detection (BFD) protocol.

Chassis without direct external mapping to a external Layer3 network will
forward traffic through a tunnel to one of the chassis acting as a gateway for
that network.

> **Note**: It is not necessary nor recommended to add mapping for external
  Layer3 networks to all chassis.  Doing so will create a scaling problem at
  the physical network layer that needs to be resolved with globally shared
  Layer2 (does not scale) or tunneling at the top-of-rack switch layer (adds
  complexity) and is generally not a recommended configuration.

Networks for use with external Layer2 connectivity should have mappings present
on all chassis with potential to host the consuming payload.

# Bugs

Please report bugs on [Launchpad][lp-ovn-chassis].

For general questions please refer to the OpenStack [Charm Guide][cg].

<!-- LINKS -->

[cdg]: https://docs.openstack.org/project-deploy-guide/charm-deployment-guide/latest/
[ovn-cdg]: https://docs.openstack.org/project-deploy-guide/charm-deployment-guide/latest/app-ovn.html
[cg]: https://docs.openstack.org/charm-guide/latest/
[charm-nova-compute]: https://jaas.ai/nova-compute
[charm-vault]: https://jaas.ai/vault/
[lp-ovn-chassis]: https://bugs.launchpad.net/charm-ovn-chassis/+filebug
[openstack-base-bundle]: https://github.com/openstack-charmers/openstack-bundles/blob/master/development/openstack-base-bionic-ussuri-ovn/bundle.yaml
