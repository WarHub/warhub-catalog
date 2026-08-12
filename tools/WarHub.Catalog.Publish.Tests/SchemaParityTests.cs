using System.Text.Json;
using WarHub.Catalog.Publish;

namespace WarHub.Catalog.Publish.Tests;

/// <summary>
/// The published JSON Schema is the public contract, but it is hand-authored beside a record that
/// generates itself -- so the two drift, silently. <c>soldSeparately</c> was emitted into
/// dist/paints.json for its whole life with no key in paint-catalog.json at all: the paint schema
/// declares no <c>additionalProperties: false</c>, so nothing failed and nothing warned; the
/// contract simply under-described its own output. Nobody notices that by reading. This closes it
/// mechanically instead, so the next field to be added is caught at the commit that adds it.
/// </summary>
public sealed class SchemaParityTests
{
    [Fact]
    public void Every_published_paint_property_is_declared_in_the_schema()
    {
        using JsonDocument schema = JsonDocument.Parse(File.ReadAllText(
            Path.Combine(AppContext.BaseDirectory, "schema", "paint-catalog.json")));
        JsonElement declared = schema.RootElement
            .GetProperty("$defs").GetProperty("paint").GetProperty("properties");

        // The key names must come from the SERIALIZER, not a hand-rolled PascalCase->camelCase
        // pass: JsonConfig.Options is what actually writes the bytes, so anything else could agree
        // with the schema while disagreeing with dist/. No property carries [JsonPropertyName]
        // today -- if one ever does, this fails loudly, which is the correct outcome.
        JsonNamingPolicy policy = JsonConfig.Options.PropertyNamingPolicy!;
        string[] emitted = [.. typeof(PaintRecord).GetProperties().Select(p => policy.ConvertName(p.Name))];

        string[] missing = [.. emitted
            .Where(name => !declared.TryGetProperty(name, out _))
            .Order(StringComparer.Ordinal)];

        Assert.Equal(Array.Empty<string>(), missing);

        // AND THE OTHER DIRECTION, because the drift runs both ways and only one of them was
        // asserted. A property REMOVED from the record leaves a key in the schema that nothing
        // ever emits -- a phantom the contract still promises, which is worse than an undeclared
        // field: a consumer can code against it and get null forever, and no publish run will
        // ever contradict them. Removals are rarer than additions, which is exactly why nobody
        // would catch this one by reading.
        string[] orphaned = [.. declared.EnumerateObject()
            .Select(p => p.Name)
            .Where(name => !emitted.Contains(name, StringComparer.Ordinal))
            .Order(StringComparer.Ordinal)];

        Assert.Equal(Array.Empty<string>(), orphaned);
    }
}
