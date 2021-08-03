# Overview

The ovn-dedicated-chassis charm provides the Open Virtual Network (OVN) local
controller, Open vSwitch Database and Switch. It is used in conjunction with
the [ovn-central][ovn-central-charm] charm.

Open vSwitch bridges for integration, external Layer2 and Layer3 connectivity
is managed by the charm.

On successful deployment the unit will be enlisted as a Chassis in the OVN
network.

The ovn-dedicated-chassis charm is a principle charm that sets up a software
gateway on a dedicated host. Alternatively, the subordinate
[ovn-chassis][ovn-chassis-charm] charm can be used.

> **Note**: The OVN charms are supported starting with OpenStack Train.

# Usage

The [OpenStack Base bundle][openstack-base-bundle] gives an example of how you
can deploy OpenStack and OVN with [Vault][vault-charm] to automate certificate
lifecycle management.

OVN makes use of Public Key Infrastructure (PKI) to authenticate and authorize
control plane communication. The charm therefore requires a Certificate
Authority to be present in the model as represented by the `certificates`
relation.

Refer to [Open Virtual Network (OVN)][cdg-ovn] in the [OpenStack Charms
Deployment Guide][cdg] for details, including deployment steps.

This charm provides the Open Virtual Network (OVN) local controller, Open
vSwitch Database and Switch.

On successful deployment the unit will be enlisted as a `Chassis` in the OVN
network.

Open vSwitch bridges for integration, external Layer2 and Layer3 connectivity
is managed by the charm.

## Network spaces

This charm supports the use of Juju network spaces.

By binding the `ovsdb` endpoint you can influence which interface will be used
for communication with the OVN Southbound DB as well as overlay traffic.

    juju deploy ovn-dedicated-chassis --bind "ovsdb=internal-space"

By binding the `data` extra-binding you can influence which interface will be
used for overlay traffic.

    juju deploy ovn-dedicated-chassis --bind "data=overlay-space"

## Port configuration

Chassis port configuration is composed of a mapping between physical network
names to bridge names (`ovn-bridge-mappings`) and individual interface to
bridge names (`bridge-interface-mappings`). There must be a match in both
configuration options before the charm will configure bridge and interfaces on
a unit.

The physical network name can be referenced when the administrator programs the
OVN logical flows, either by talking directly to the Northbound database, or by
interfacing with a Cloud Management System (CMS).

Networks for use with external Layer3 connectivity should have mappings on
chassis located in the vicinity of the datacenter border gateways. Having two
or more chassis with mappings for a Layer3 network will have OVN automatically
configure highly available routers with liveness detection provided by the
Bidirectional Forwarding Detection (BFD) protocol.

Chassis without direct external mapping to a external Layer3 network will
forward traffic through a tunnel to one of the chassis acting as a gateway for
that network.

> **Note**: It is not necessary, nor recommended, to add mapping for external
  Layer3 networks to all chassis. Doing so will create a scaling problem at the
  physical network layer that needs to be resolved with globally shared Layer2
  (does not scale) or tunneling at the top-of-rack switch layer (adds
  complexity) and is generally not a recommended configuration.

Networks for use with external Layer2 connectivity should have mappings present
on all chassis with potential to host the consuming payload.

## Deferred service events

Operational or maintenance procedures applied to a cloud often lead to the
restarting of various OpenStack services and/or the calling of certain charm
hooks. Although normal, such events can be undesirable due to the service
interruptions they can cause.

The deferred service events feature provides the operator the choice of
preventing these service restarts and hook calls from occurring, which can then
be resolved at a more opportune time.

See the [Deferred service events][cdg-deferred-service-events] page in the
[OpenStack Charms Deployment Guide][cdg] for an in-depth treatment of this
feature.

# Bugs

Please report bugs on [Launchpad][lp-ovn-dedicated-chassis].

For general questions please refer to the [OpenStack Charm Guide][cg].

<!-- LINKS -->

[cg]: https://docs.openstack.org/charm-guide/latest/
[cdg]: https://docs.openstack.org/project-deploy-guide/charm-deployment-guide/latest/
[cdg-ovn]: https://docs.openstack.org/project-deploy-guide/charm-deployment-guide/latest/app-ovn.html
[vault-charm]: https://jaas.ai/vault/
[lp-ovn-dedicated-chassis]: https://bugs.launchpad.net/charm-ovn-dedicated-chassis/+filebug
[ovn-central-charm]: https://jaas.ai/ovn-central
[ovn-chassis-charm]: https://jaas.ai/ovn-chassis
[openstack-base-bundle]: https://github.com/openstack-charmers/openstack-bundles/blob/master/development/openstack-base-bionic-ussuri-ovn/bundle.yaml
[cdg-deferred-service-events]: https://docs.openstack.org/project-deploy-guide/charm-deployment-guide/latest/deferred-events.html
