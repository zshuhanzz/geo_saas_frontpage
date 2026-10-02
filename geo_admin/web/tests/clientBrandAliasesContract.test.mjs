import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const root = new URL("../src/", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");
const readWeb = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

test("Admin API exposes canonical per-brand Alias reads and writes", () => {
    const source = read("api/client.ts");
    const generated = read("api/openapi.d.ts");

    assert.match(source, /type ClientCreate = Schemas\["ClientCreate"\]/);
    assert.match(source, /type ClientUpdate = Schemas\["ClientUpdate"\]/);
    assert.match(source, /export type ClientBrand = Schemas\["ClientBrandOut"\]/);
    assert.doesNotMatch(source, /export interface ClientBrand/);
    assert.match(source, /\/clients\/\$\{clientId\}\/brands/);
    assert.match(source, /\/brands\/\$\{brandId\}\/aliases/);
    assert.match(generated, /ClientBrandOut:/);
    assert.match(generated, /BrandAliasesUpdate:/);
    assert.match(generated, /"\/api\/clients\/\{client_id\}\/brands":/);
    assert.match(generated, /"\/api\/clients\/\{client_id\}\/brands\/\{brand_id\}\/aliases":/);

    const createSchema = generated.match(/ClientCreate:\s*\{(?<body>[\s\S]*?)\n\s*\};/)?.groups?.body || "";
    const updateSchema = generated.match(/ClientUpdate:\s*\{(?<body>[\s\S]*?)\n\s*\};/)?.groups?.body || "";
    assert.doesNotMatch(createSchema, /aliases\??:/);
    assert.doesNotMatch(updateSchema, /aliases\??:/);
});

test("Client Info no longer renders or submits legacy client aliases", () => {
    const source = read("pages/ClientsPage.tsx");

    assert.doesNotMatch(source, /editAliases|setEditAliases|aliasInput|setAliasInput/);
    assert.doesNotMatch(source, /aliases:\s*editAliases/);
    assert.match(source, /<ClientBrandAliases\s+clientId=\{sc\.id\}/);
});

test("Workspace creation sends only the exact ClientCreate fields used by Admin", () => {
    const source = read("pages/ClientsPage.tsx");
    const generated = read("api/openapi.d.ts");
    const createCall = source.match(/await createClient\(\{(?<body>[\s\S]*?)\n\s*\}\);/)?.groups?.body || "";
    const createSchema = generated.match(/ClientCreate:\s*\{(?<body>[\s\S]*?)\n\s*\};/)?.groups?.body || "";

    assert.match(createCall, /name:\s*newClientName/);
    assert.match(createCall, /client_prompt_quota:\s*newClientQuota/);
    assert.match(createCall, /config_platforms:\s*\[\]/);
    assert.match(createCall, /config_countries:\s*\[\]/);
    assert.match(createCall, /config_languages:\s*\[\]/);
    assert.doesNotMatch(createCall, /peers\s*:/);
    assert.doesNotMatch(createCall, /aliases\s*:/);
    assert.doesNotMatch(createSchema, /peers\??:/);
    assert.doesNotMatch(createSchema, /aliases\??:/);
});

test("per-brand editor distinguishes Own and Shadow brands and has independent status", () => {
    const source = read("components/ClientBrandAliases.tsx");

    assert.match(source, /Own Brands/);
    assert.match(source, /Shadow Brands/);
    assert.match(source, /saving/);
    assert.match(source, /success/);
    assert.match(source, /error/);
    assert.match(source, /refresh/);
});

test("Admin typecheck executes the referenced app and node projects", () => {
    const packageJson = JSON.parse(readWeb("package.json"));

    assert.equal(packageJson.scripts.typecheck, "tsc -b --pretty false");
});
