namespace WarHub.Catalog.Publish.Tests;

/// <summary>
/// The happy path (every generated document validating) is covered by <see cref="PublishTests"/>
/// via the fixture's full publish run. These cover the rejection path: a schema violation must
/// fail the build with a message that actually names the offending location.
/// </summary>
public sealed class SchemaValidatorTests
{
    private static SchemaValidator Validator()
        => SchemaValidator.LoadFrom(Path.Combine(AppContext.BaseDirectory, "schema"));

    [Fact]
    public void Valid_document_passes()
    {
        Validator().Validate("manifest", ValidManifest, "manifest.json");
    }

    [Fact]
    public void Missing_required_property_is_reported()
    {
        // "files" is required by the manifest schema.
        const string json = """
            {"schemaVersion":"1","kind":"manifest","version":"1.0.0","generatedAt":"2026-07-04T00:00:00Z",
             "source":{"repo":"WarHub/warhub-catalog"},"counts":{}}
            """;

        var ex = Assert.Throws<InvalidOperationException>(
            () => Validator().Validate("manifest", json, "manifest.json"));

        Assert.Contains("manifest.json", ex.Message, StringComparison.Ordinal);
        Assert.Contains("files", ex.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Nested_constraint_violation_reports_instance_location()
    {
        // sha256 must match ^[0-9a-f]{64}$ — this one is far too short.
        const string json = """
            {"schemaVersion":"1","kind":"manifest","version":"1.0.0","generatedAt":"2026-07-04T00:00:00Z",
             "source":{"repo":"WarHub/warhub-catalog"},"counts":{},
             "files":[{"path":"products.json","kind":"products","bytes":10,"sha256":"abc"}]}
            """;

        var ex = Assert.Throws<InvalidOperationException>(
            () => Validator().Validate("manifest", json, "manifest.json"));

        // The error detail must pinpoint where it failed, not just say "invalid".
        Assert.Contains("/files/0/sha256", ex.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Unknown_schema_name_throws()
    {
        var ex = Assert.Throws<InvalidOperationException>(
            () => Validator().Validate("no-such-schema", ValidManifest, "whatever.json"));

        Assert.Contains("no-such-schema", ex.Message, StringComparison.Ordinal);
    }

    private const string ValidManifest = """
        {"schemaVersion":"1","kind":"manifest","version":"1.0.0","generatedAt":"2026-07-04T00:00:00Z",
         "source":{"repo":"WarHub/warhub-catalog"},"counts":{"products":2},
         "files":[{"path":"products.json","kind":"products","bytes":10,
                   "sha256":"0000000000000000000000000000000000000000000000000000000000000000"}]}
        """;
}
