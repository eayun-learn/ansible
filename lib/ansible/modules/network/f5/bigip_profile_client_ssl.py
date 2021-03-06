#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2017 F5 Networks Inc.
# GNU General Public License v3.0 (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}

DOCUMENTATION = r'''
---
module: bigip_profile_client_ssl
short_description: Manages client SSL profiles on a BIG-IP
description: Manages client SSL profiles on a BIG-IP.
version_added: "2.5"
options:
  name:
    description:
      - Specifies the name of the profile.
    required: True
  parent:
    description:
      - The parent template of this monitor template. Once this value has
        been set, it cannot be changed. By default, this value is the C(clientssl)
        parent on the C(Common) partition.
    default: "/Common/clientssl"
  ciphers:
    description:
      - Specifies the list of ciphers that the system supports. When creating a new
        profile, the default cipher list is C(DEFAULT).
  cert_key_chain:
    description:
      - One or more certificates and keys to associate with the SSL profile. This
        option is always a list. The keys in the list dictate the details of the
        client/key/chain combination. Note that BIG-IPs can only have one of each
        type of each certificate/key type. This means that you can only have one
        RSA, one DSA, and one ECDSA per profile. If you attempt to assign two
        RSA, DSA, or ECDSA certificate/key combo, the device will reject this.
      - This list is a complex list that specifies a number of keys. There are several supported keys.
    suboptions:
      cert:
        description:
          - Specifies a cert name for use.
        required: True
      key:
        description:
          - Contains a key name.
        required: True
      chain:
        description:
          - Contains a certificate chain that is relevant to the certificate and key
            mentioned earlier.
          - This key is optional.
      passphrase:
        description:
          - Contains the passphrase of the key file, should it require one.
          - Passphrases are encrypted on the remote BIG-IP device. Therefore, there is no way
            to compare them when updating a client SSL profile. Due to this, if you specify a
            passphrase, this module will always register a C(changed) event.
  partition:
    description:
      - Device partition to manage resources on.
    required: False
    default: 'Common'
    version_added: 2.5
notes:
  - Requires the f5-sdk Python package on the host. This is as easy as pip
    install f5-sdk.
  - Requires BIG-IP software version >= 12
requirements:
  - f5-sdk >= 2.2.3
extends_documentation_fragment: f5
author:
  - Tim Rupp (@caphrim007)
'''

EXAMPLES = r'''
- name: Create client SSL profile
  bigip_profile_client_ssl:
    state: present
    server: lb.mydomain.com
    user: admin
    password: secret
    name: my_profile
  delegate_to: localhost

- name: Create client SSL profile with specific ciphers
  bigip_profile_client_ssl:
    state: present
    server: lb.mydomain.com
    user: admin
    password: secret
    name: my_profile
    ciphers: "!SSLv3:!SSLv2:ECDHE+AES-GCM+SHA256:ECDHE-RSA-AES128-CBC-SHA"
  delegate_to: localhost

- name: Create a client SSL profile with a cert/key/chain setting
  bigip_profile_client_ssl:
    state: present
    server: lb.mydomain.com
    user: admin
    password: secret
    name: my_profile
    cert_key_chain:
      - cert: bigip_ssl_cert1
        key: bigip_ssl_key1
        chain: bigip_ssl_cert1
  delegate_to: localhost
'''

RETURN = r'''
ciphers:
  description: The ciphers applied to the profile.
  returned: changed
  type: string
  sample: "!SSLv3:!SSLv2:ECDHE+AES-GCM+SHA256:ECDHE-RSA-AES128-CBC-SHA"
'''

import os

from ansible.module_utils.f5_utils import AnsibleF5Client
from ansible.module_utils.f5_utils import AnsibleF5Parameters
from ansible.module_utils.f5_utils import HAS_F5SDK
from ansible.module_utils.f5_utils import F5ModuleError
from ansible.module_utils.six import iteritems
from collections import defaultdict

try:
    from ansible.module_utils.f5_utils import iControlUnexpectedHTTPError
except ImportError:
    HAS_F5SDK = False


class Parameters(AnsibleF5Parameters):
    api_map = {
        'certKeyChain': 'cert_key_chain',
        'ocspStapling': 'ocsp_stapling'
    }

    api_attributes = [
        'ciphers', 'certKeyChain', 'ocspStapling'
    ]

    returnables = [
        'ciphers', 'ocsp_stapling'
    ]

    updatables = [
        'ciphers', 'cert_key_chain', 'ocsp_stapling'
    ]

    def __init__(self, params=None):
        self._values = defaultdict(lambda: None)
        self._values['__warnings'] = []
        if params:
            self.update(params=params)

    def update(self, params=None):
        if params:
            for k, v in iteritems(params):
                if self.api_map is not None and k in self.api_map:
                    map_key = self.api_map[k]
                else:
                    map_key = k

                # Handle weird API parameters like `dns.proxy.__iter__` by
                # using a map provided by the module developer
                class_attr = getattr(type(self), map_key, None)
                if isinstance(class_attr, property):
                    # There is a mapped value for the api_map key
                    if class_attr.fset is None:
                        # If the mapped value does not have
                        # an associated setter
                        self._values[map_key] = v
                    else:
                        # The mapped value has a setter
                        setattr(self, map_key, v)
                else:
                    # If the mapped value is not a @property
                    self._values[map_key] = v

    def api_params(self):
        result = {}
        for api_attribute in self.api_attributes:
            if self.api_map is not None and api_attribute in self.api_map:
                result[api_attribute] = getattr(self, self.api_map[api_attribute])
            else:
                result[api_attribute] = getattr(self, api_attribute)
        result = self._filter_params(result)
        return result


class ModuleParameters(Parameters):
    def _fqdn_name(self, value):
        if value is not None and not value.startswith('/'):
            return '/{0}/{1}'.format(self.partition, value)
        return value

    def _key_filename(self, name):
        if name.endswith('.key'):
            return name
        else:
            return name + '.key'

    def _cert_filename(self, name):
        if name.endswith('.crt'):
            return name
        else:
            return name + '.crt'

    def _get_chain_value(self, item):
        if 'chain' not in item or item['chain'] == 'none':
            result = 'none'
        else:
            result = self._cert_filename(self._fqdn_name(item['chain']))
        return result

    @property
    def parent(self):
        if self._values['parent'] is None:
            return None
        result = self._fqdn_name(self._values['parent'])
        return result

    @property
    def cert_key_chain(self):
        if self._values['cert_key_chain'] is None:
            return None
        result = []
        for item in self._values['cert_key_chain']:
            if 'key' in item and 'cert' not in item:
                raise F5ModuleError(
                    "When providing a 'key', you must also provide a 'cert'"
                )
            if 'cert' in item and 'key' not in item:
                raise F5ModuleError(
                    "When providing a 'cert', you must also provide a 'key'"
                )
            key = self._key_filename(item['key'])
            cert = self._cert_filename(item['cert'])
            chain = self._get_chain_value(item)
            name = os.path.basename(cert)
            filename, ex = os.path.splitext(name)
            tmp = {
                'name': filename,
                'cert': self._fqdn_name(cert),
                'key': self._fqdn_name(key),
                'chain': chain
            }
            if 'passphrase' in item:
                tmp['passphrase'] = item['passphrase']
            result.append(tmp)
        result = sorted(result, key=lambda x: x['name'])
        return result


class ApiParameters(Parameters):
    @property
    def cert_key_chain(self):
        if self._values['cert_key_chain'] is None:
            return None
        result = []
        for item in self._values['cert_key_chain']:
            tmp = dict(
                name=item['name'],
            )
            for x in ['cert', 'key', 'chain', 'passphrase']:
                if x in item:
                    tmp[x] = item[x]
            result.append(tmp)
        result = sorted(result, key=lambda x: x['name'])
        return result


class Changes(Parameters):
    def to_return(self):
        result = {}
        try:
            for returnable in self.returnables:
                result[returnable] = getattr(self, returnable)
            result = self._filter_params(result)
        except Exception:
            pass
        return result


class UsableChanges(Changes):
    pass


class ReportableChanges(Changes):
    pass


class Difference(object):
    def __init__(self, want, have=None):
        self.want = want
        self.have = have

    def compare(self, param):
        try:
            result = getattr(self, param)
            return result
        except AttributeError:
            result = self.__default(param)
            return result

    def __default(self, param):
        attr1 = getattr(self.want, param)
        try:
            attr2 = getattr(self.have, param)
            if attr1 != attr2:
                return attr1
        except AttributeError:
            return attr1

    def to_tuple(self, items):
        result = []
        for x in items:
            tmp = [(str(k), str(v)) for k, v in iteritems(x)]
            result += tmp
        return result

    def _diff_complex_items(self, want, have):
        if want == [] and have is None:
            return None
        if want is None:
            return None
        w = self.to_tuple(want)
        h = self.to_tuple(have)
        if set(w).issubset(set(h)):
            return None
        else:
            return want

    @property
    def parent(self):
        if self.want.parent != self.have.parent:
            raise F5ModuleError(
                "The parent profile cannot be changed"
            )

    @property
    def cert_key_chain(self):
        result = self._diff_complex_items(self.want.cert_key_chain, self.have.cert_key_chain)
        return result


class ModuleManager(object):
    def __init__(self, client):
        self.client = client
        self.want = ModuleParameters(params=self.client.module.params)
        self.have = ApiParameters()
        self.changes = UsableChanges()

    def _set_changed_options(self):
        changed = {}
        for key in Parameters.returnables:
            if getattr(self.want, key) is not None:
                changed[key] = getattr(self.want, key)
        if changed:
            self.changes = UsableChanges(changed)

    def _update_changed_options(self):
        diff = Difference(self.want, self.have)
        updatables = Parameters.updatables
        changed = dict()
        for k in updatables:
            change = diff.compare(k)
            if change is None:
                continue
            else:
                if isinstance(change, dict):
                    changed.update(change)
                else:
                    changed[k] = change
        if changed:
            self.changes = UsableChanges(changed)
            return True
        return False

    def exec_module(self):
        changed = False
        result = dict()
        state = self.want.state

        try:
            if state == "present":
                changed = self.present()
            elif state == "absent":
                changed = self.absent()
        except iControlUnexpectedHTTPError as e:
            raise F5ModuleError(str(e))

        reportable = ReportableChanges(self.changes.to_return())
        changes = reportable.to_return()
        result.update(**changes)
        result.update(dict(changed=changed))
        self._announce_deprecations(result)
        return result

    def _announce_deprecations(self, result):
        warnings = result.pop('__warnings', [])
        for warning in warnings:
            self.client.module.deprecate(
                msg=warning['msg'],
                version=warning['version']
            )

    def present(self):
        if self.exists():
            return self.update()
        else:
            return self.create()

    def create(self):
        self._set_changed_options()
        if self.want.ciphers is None:
            self.want.update({'ciphers': 'DEFAULT'})
        if self.client.check_mode:
            return True
        self.create_on_device()
        return True

    def should_update(self):
        result = self._update_changed_options()
        if result:
            return True
        return False

    def update(self):
        self.have = self.read_current_from_device()
        if not self.should_update():
            return False
        if self.client.check_mode:
            return True
        self.update_on_device()
        return True

    def absent(self):
        if self.exists():
            return self.remove()
        return False

    def remove(self):
        if self.client.check_mode:
            return True
        self.remove_from_device()
        if self.exists():
            raise F5ModuleError("Failed to delete the profile.")
        return True

    def read_current_from_device(self):
        resource = self.client.api.tm.ltm.profile.client_ssls.client_ssl.load(
            name=self.want.name,
            partition=self.want.partition
        )
        result = resource.attrs
        return ApiParameters(result)

    def exists(self):
        result = self.client.api.tm.ltm.profile.client_ssls.client_ssl.exists(
            name=self.want.name,
            partition=self.want.partition
        )
        return result

    def update_on_device(self):
        params = self.changes.api_params()
        result = self.client.api.tm.ltm.profile.client_ssls.client_ssl.load(
            name=self.want.name,
            partition=self.want.partition
        )
        result.modify(**params)

    def create_on_device(self):
        params = self.want.api_params()
        self.client.api.tm.ltm.profile.client_ssls.client_ssl.create(
            name=self.want.name,
            partition=self.want.partition,
            **params
        )

    def remove_from_device(self):
        result = self.client.api.tm.ltm.profile.client_ssls.client_ssl.load(
            name=self.want.name,
            partition=self.want.partition
        )
        if result:
            result.delete()


class ArgumentSpec(object):
    def __init__(self):
        self.supports_check_mode = True
        self.argument_spec = dict(
            name=dict(required=True),
            parent=dict(),
            ciphers=dict(),
            cert_key_chain=dict(
                type='list',
                options=dict(
                    cert=dict(required=True),
                    key=dict(required=True),
                    chain=dict(),
                    passphrase=dict()
                )
            )
        )
        self.f5_product_name = 'bigip'


def cleanup_tokens(client):
    try:
        resource = client.api.shared.authz.tokens_s.token.load(
            name=client.api.icrs.token
        )
        resource.delete()
    except Exception:
        pass


def main():
    if not HAS_F5SDK:
        raise F5ModuleError("The python f5-sdk module is required")

    spec = ArgumentSpec()

    client = AnsibleF5Client(
        argument_spec=spec.argument_spec,
        supports_check_mode=spec.supports_check_mode,
        f5_product_name=spec.f5_product_name
    )

    try:
        mm = ModuleManager(client)
        results = mm.exec_module()
        cleanup_tokens(client)
        client.module.exit_json(**results)
    except F5ModuleError as e:
        cleanup_tokens(client)
        client.module.fail_json(msg=str(e))


if __name__ == '__main__':
    main()
