import pytest

from maasserver import vault
from maasserver.models import Config, Secret
from maasserver.secrets import SecretManager, SecretNotFound, UnknownSecret
from maasserver.testing.factory import factory


class MockVaultClient:
    def __init__(self):
        self.store = {}

    def set(self, path, value):
        self.store[path] = value

    def get(self, path):
        try:
            return self.store[path]
        except KeyError:
            raise SecretNotFound(path)

    def delete(self, path):
        self.store.pop(path, None)


@pytest.fixture
def vault_client(request):
    if request.param:
        yield MockVaultClient()
    else:
        yield None


@pytest.mark.django_db
@pytest.mark.parametrize("vault_client", [True, False], indirect=True)
class TestSecretManager:
    def set_secret(self, vault_client, path, value):
        if vault_client:
            vault_client.store[path] = value
        else:
            Secret.objects.create(path=path, value=value)

    def assert_secrets(self, vault_client, secrets):
        if vault_client:
            assert vault_client.store == secrets
        else:
            assert dict(Secret.objects.values_list("path", "value")) == secrets

    def test_uses_provided_client_instead_of_making_new(
        self, vault_client, mocker
    ):
        get_vault_mock = mocker.patch.object(vault, "get_region_vault_client")
        get_vault_mock.return_value = vault_client

        Config.objects.set_config("vault_enabled", True)
        SecretManager(vault_client=vault_client)
        Config.objects.set_config("vault_enabled", False)

        get_vault_mock.assert_not_called()

    def test_get_composite_secret_with_model(self, vault_client):
        value = {"foo": "bar"}
        node = factory.make_Node()
        self.set_secret(vault_client, f"node/{node.id}/deploy-metadata", value)
        manager = SecretManager(vault_client=vault_client)
        assert (
            manager.get_composite_secret("deploy-metadata", obj=node) == value
        )

    def test_get_composite_secret_with_model_not_found(self, vault_client):
        node = factory.make_Node()
        manager = SecretManager(vault_client=vault_client)
        with pytest.raises(SecretNotFound):
            manager.get_composite_secret("deploy-metadata", obj=node)

    def test_get_composite_secret_with_model_not_found_default(
        self, vault_client
    ):
        node = factory.make_Node()
        manager = SecretManager(vault_client=vault_client)
        assert (
            manager.get_composite_secret(
                "deploy-metadata", obj=node, default="default"
            )
            == "default"
        )

    def test_get_composite_secret_global(self, vault_client):
        value = {"bar": "baz"}
        self.set_secret(vault_client, "global/tls", value)
        manager = SecretManager(vault_client=vault_client)
        assert manager.get_composite_secret("tls") == value

    def test_get_composite_secret_global_not_found(self, vault_client):
        manager = SecretManager(vault_client=vault_client)
        with pytest.raises(SecretNotFound):
            manager.get_composite_secret("tls")

    def test_get_composite_secret_global_not_found_default(self, vault_client):
        manager = SecretManager(vault_client=vault_client)
        assert (
            manager.get_composite_secret("tls", default="default") == "default"
        )

    def test_get_composite_secret_global_unknown(self, vault_client):
        manager = SecretManager(vault_client)
        with pytest.raises(UnknownSecret):
            manager.get_composite_secret("unknown")

    def test_get_simple_secret_with_model(self, vault_client):
        node = factory.make_Node()
        self.set_secret(
            vault_client, f"node/{node.id}/deploy-metadata", {"secret": "foo"}
        )
        manager = SecretManager(vault_client=vault_client)
        assert manager.get_simple_secret("deploy-metadata", obj=node) == "foo"

    def test_get_simple_secret_with_model_not_found(self, vault_client):
        node = factory.make_Node()
        manager = SecretManager(vault_client=vault_client)
        with pytest.raises(SecretNotFound):
            manager.get_simple_secret("deploy-metadata", obj=node)

    def test_get_simple_secret_with_model_not_found_default(
        self, vault_client
    ):
        node = factory.make_Node()
        manager = SecretManager(vault_client=vault_client)
        assert (
            manager.get_simple_secret(
                "deploy-metadata", obj=node, default="bar"
            )
            == "bar"
        )

    def test_get_simple_secret_global(self, vault_client):
        self.set_secret(vault_client, "global/omapi-key", {"secret": "bar"})
        manager = SecretManager(vault_client=vault_client)
        assert manager.get_simple_secret("omapi-key") == "bar"

    def test_get_simple_secret_global_not_found(self, vault_client):
        manager = SecretManager(vault_client=vault_client)
        with pytest.raises(SecretNotFound):
            manager.get_simple_secret("omapi-key")

    def test_get_simple_secret_global_not_found_default(self, vault_client):
        manager = SecretManager(vault_client=vault_client)
        assert manager.get_simple_secret("omapi-key", default="bar") == "bar"

    def test_get_simple_secret_global_not_found_unknown(self, vault_client):
        manager = SecretManager(vault_client=vault_client)
        with pytest.raises(UnknownSecret):
            manager.get_simple_secret("unknown")

    def test_set_composite_secret_with_model(self, vault_client):
        node = factory.make_Node()
        manager = SecretManager(vault_client=vault_client)
        value = {"bar": "baz"}
        manager.set_composite_secret("deploy-metadata", value, obj=node)
        self.assert_secrets(
            vault_client, {f"node/{node.id}/deploy-metadata": value}
        )

    def test_set_composite_secret_global(self, vault_client):
        manager = SecretManager(vault_client=vault_client)
        value = {"bar": "baz"}
        manager.set_composite_secret("tls", value)
        self.assert_secrets(vault_client, {"global/tls": value})

    def test_set_simple_secret_with_model(self, vault_client):
        node = factory.make_Node()
        manager = SecretManager(vault_client=vault_client)
        value = {"bar": "baz"}
        manager.set_simple_secret("deploy-metadata", value, obj=node)
        self.assert_secrets(
            vault_client,
            {f"node/{node.id}/deploy-metadata": {"secret": value}},
        )

    def test_set_simple_secret_with_model_unknown(self, vault_client):
        node = factory.make_Node()
        manager = SecretManager(vault_client=vault_client)
        with pytest.raises(UnknownSecret):
            manager.set_simple_secret("unknown", {"bar, baz"}, obj=node)

    def test_set_simple_secret_global(self, vault_client):
        manager = SecretManager(vault_client=vault_client)
        manager.set_simple_secret("omapi-key", "foo")
        self.assert_secrets(
            vault_client, {"global/omapi-key": {"secret": "foo"}}
        )

    def test_set_simple_secret_global_unknown(self, vault_client):
        manager = SecretManager(vault_client=vault_client)
        with pytest.raises(UnknownSecret):
            manager.set_simple_secret("unknown", "foo")

    def test_delete_secret_with_model(self, vault_client):
        node = factory.make_Node()
        manager = SecretManager(vault_client=vault_client)
        self.set_secret(
            vault_client, f"node/{node.id}/deploy-metadata", {"foo": "bar"}
        )
        manager.delete_secret("deploy-metadata", obj=node)
        self.assert_secrets(vault_client, {})

    def test_delete_secret_with_model_unknown(self, vault_client):
        node = factory.make_Node()
        manager = SecretManager(vault_client=vault_client)
        with pytest.raises(UnknownSecret):
            manager.delete_secret("unknown", obj=node)

    def test_delete_secret_global(self, vault_client):
        manager = SecretManager(vault_client=vault_client)
        self.set_secret(vault_client, "global/omapi-key", "foo")
        manager.delete_secret("omapi-key")
        self.assert_secrets(vault_client, {})

    def test_delete_secret_global_unknown(self, vault_client):
        manager = SecretManager(vault_client=vault_client)
        with pytest.raises(UnknownSecret):
            manager.delete_secret("unknown")

    def test_delete_all_object_secrets_only_object(self, vault_client):
        node1 = factory.make_Node()
        node2 = factory.make_Node()
        manager = SecretManager(vault_client=vault_client)
        value = {"foo": "bar"}
        manager.set_simple_secret("deploy-metadata", value, obj=node1)
        manager.set_simple_secret("deploy-metadata", value, obj=node2)
        manager.delete_all_object_secrets(node1)
        self.assert_secrets(
            vault_client,
            {f"node/{node2.id}/deploy-metadata": {"secret": value}},
        )

    def test_delete_all_object_secrets_only_known(self, vault_client):
        node = factory.make_Node()
        manager = SecretManager(vault_client=vault_client)
        manager.set_simple_secret("deploy-metadata", "foo", obj=node)
        self.set_secret(
            vault_client, f"node/{node.id}/unknown", {"foo": "bar"}
        )
        manager.delete_all_object_secrets(node)
        self.assert_secrets(
            vault_client, {f"node/{node.id}/unknown": {"foo": "bar"}}
        )
