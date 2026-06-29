import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import scan_source_ids as s


def test_module_from_path_business():
    p = "service/business/account/src/p_login/res/layout/fragment_password_login.xml"
    assert s.module_from_path(p) == "account"


def test_module_from_path_accessories():
    assert s.module_from_path("accessories/ketang/src/main/res/layout/a.xml") == "ketang"


def test_parse_layout_ids():
    xml = '''
    <Button android:id="@+id/account_sign_btn"/>
    <EditText android:id="@+id/account_enter_et"/>
    <View android:id="@id/tab_title"/>
    <Button android:id="@+id/account_sign_btn"/>
    '''
    assert s.parse_layout_ids(xml) == ["account_enter_et", "account_sign_btn", "tab_title"]


def test_parse_layout_refs_r_layout():
    src = "setContentView(R.layout.fragment_password_login)"
    assert "fragment_password_login" in s.parse_layout_refs(src)


def test_parse_layout_refs_viewbinding():
    src = "val b = FragmentPasswordLoginBinding.inflate(inflater)"
    assert "fragment_password_login" in s.parse_layout_refs(src)


def test_camel_to_snake():
    assert s.camel_to_snake("FragmentPasswordLogin") == "fragment_password_login"


def test_page_name_from_path():
    assert s.page_name_from_path("x/y/LoginActivity.kt") == "LoginActivity"
    assert s.page_name_from_path("x/LoginFragment.java") == "LoginFragment"


def test_build_attribution_links_id_to_page():
    layout_to_ids = {"fragment_password_login": ["account_sign_btn", "phone_et"]}
    layout_to_pages = {"fragment_password_login": {"LoginFragment"}}
    id_to_module = {"account_sign_btn": "account", "phone_et": "account"}
    attr = s.build_attribution(layout_to_ids, layout_to_pages, id_to_module)
    assert attr["account_sign_btn"]["pages"] == ["LoginFragment"]
    assert attr["account_sign_btn"]["module"] == "account"
    assert attr["account_sign_btn"]["layouts"] == ["fragment_password_login"]


def test_join_with_apk_counts_coverage():
    apk_ids = ["account_sign_btn", "lib_only_id"]
    attribution = {
        "account_sign_btn": {"module": "account", "layouts": ["l"], "pages": ["LoginFragment"]},
    }
    res = s.join_with_apk(apk_ids, attribution, "com.gaotu100.superclass")
    assert res["stats"]["apk_total"] == 2
    assert res["stats"]["source_attributed"] == 1
    assert res["stats"]["page_linked"] == 1
    entry = next(e for e in res["enriched"] if e["id"] == "account_sign_btn")
    assert entry["selector"] == "com.gaotu100.superclass:id/account_sign_btn"
