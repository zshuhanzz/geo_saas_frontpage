from pathlib import Path


WEB_ROOT = Path(__file__).parents[1] / "web" / "src"


def _read(relative_path: str) -> str:
    return (WEB_ROOT / relative_path).read_text(encoding="utf-8")


def test_settings_orchestrator_wires_all_product_activation_apis() -> None:
    source = _read("pages/SettingsPage.tsx")

    for api_name in (
        "updateOwnProduct",
        "updateShadowBrandProduct",
        "updatePeerProduct",
    ):
        assert api_name in source

    assert "handleSetOwnProductActive" in source
    assert "handleSetShadowProductActive" in source
    assert "handleSetPeerProductActive" in source
    assert "is_active" in source


def test_product_rows_expose_inactive_state_and_reactivation_action() -> None:
    product_row = _read("pages/SettingsPage.parts/ProductRow.tsx")
    own_card = _read("pages/SettingsPage.parts/OwnProductCard.tsx")

    for source in (product_row, own_card):
        assert "product.is_active" in source
        assert "products.statusInactive" in source
        assert "products.reactivate" in source
        assert "products.deactivate" in source


def test_own_products_expose_explicit_brand_ownership_for_sentiment() -> None:
    settings = _read("pages/SettingsPage.tsx")
    topics_tab = _read("pages/SettingsPage.parts/TopicsTab.tsx")
    own_card = _read("pages/SettingsPage.parts/OwnProductCard.tsx")
    editor = _read("components/settings/ProductEditor.tsx")

    assert "ownBrands={ownBrands}" in settings
    assert "owner_brand_id" in topics_tab
    assert "onSetOwner" in own_card
    assert 'role === "own"' in editor
    assert "products.ownerBrand" in editor


def test_sentiment_ownership_ui_only_treats_active_own_brands_as_eligible() -> None:
    settings = _read("pages/SettingsPage.tsx")
    own_card = _read("pages/SettingsPage.parts/OwnProductCard.tsx")
    suggestions = _read("components/settings/SuggestionsPanel.tsx")

    assert "activeOwnBrands" in settings
    assert "!b.is_shadow && b.is_active" in settings
    assert "ownerIsActive" in own_card
    assert "variant={product.owner_brand_id ?" not in own_card
    assert "own_product: { needTopic: true, needBrand: true" in suggestions
    assert 'item.candidate_type === "own_product" ? false : true' in suggestions


def test_product_delete_uses_custom_confirmation_not_native_dialog() -> None:
    source = _read("pages/SettingsPage.tsx")

    assert "useConfirm" in source
    assert "products.deleteConfirmDescription" in source
    assert "window.confirm" not in source
