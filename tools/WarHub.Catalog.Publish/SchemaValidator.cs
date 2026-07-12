using System.Text.Json;
using Json.Schema;

namespace WarHub.Catalog.Publish;

/// <summary>
/// Validates generated documents against the authored JSON Schemas. A schema
/// violation fails the build so malformed artifacts never get published.
/// </summary>
internal sealed class SchemaValidator
{
    private readonly Dictionary<string, JsonSchema> _schemas = new(StringComparer.Ordinal);

    private SchemaValidator() { }

    public static SchemaValidator LoadFrom(string schemaDir)
    {
        // Build into a registry owned by this instance. The default is a process-wide global
        // registry that refuses to re-register an $id, which would make a second LoadFrom in
        // the same process throw.
        var options = new BuildOptions { SchemaRegistry = new SchemaRegistry() };

        var v = new SchemaValidator();
        foreach (string file in Directory.EnumerateFiles(schemaDir, "*.json"))
        {
            v._schemas[Path.GetFileNameWithoutExtension(file)] = JsonSchema.FromText(File.ReadAllText(file), options);
        }

        return v;
    }

    public void Validate(string schemaName, string json, string relPath)
    {
        if (!_schemas.TryGetValue(schemaName, out JsonSchema? schema))
        {
            throw new InvalidOperationException($"No schema '{schemaName}' loaded (validating {relPath}).");
        }

        using JsonDocument doc = JsonDocument.Parse(json);
        EvaluationResults results = schema.Evaluate(doc.RootElement, new EvaluationOptions { OutputFormat = OutputFormat.List });
        if (!results.IsValid)
        {
            IEnumerable<string> errors = (results.Details ?? [])
                .Where(d => d.Errors is { Count: > 0 })
                .SelectMany(d => d.Errors!.Select(e => $"{d.InstanceLocation}: {e.Value}"))
                .Distinct()
                .Take(10);
            throw new InvalidOperationException(
                $"{relPath} failed schema '{schemaName}':\n  " + string.Join("\n  ", errors));
        }
    }
}
