using System.Text.Json.Nodes;
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
        var v = new SchemaValidator();
        foreach (string file in Directory.EnumerateFiles(schemaDir, "*.json"))
        {
            v._schemas[Path.GetFileNameWithoutExtension(file)] = JsonSchema.FromText(File.ReadAllText(file));
        }

        return v;
    }

    public void Validate(string schemaName, string json, string relPath)
    {
        if (!_schemas.TryGetValue(schemaName, out JsonSchema? schema))
        {
            throw new InvalidOperationException($"No schema '{schemaName}' loaded (validating {relPath}).");
        }

        JsonNode? node = JsonNode.Parse(json);
        EvaluationResults results = schema.Evaluate(node, new EvaluationOptions { OutputFormat = OutputFormat.List });
        if (!results.IsValid)
        {
            IEnumerable<string> errors = results.Details
                .Where(d => d.HasErrors)
                .SelectMany(d => d.Errors!.Select(e => $"{d.InstanceLocation}: {e.Value}"))
                .Distinct()
                .Take(10);
            throw new InvalidOperationException(
                $"{relPath} failed schema '{schemaName}':\n  " + string.Join("\n  ", errors));
        }
    }
}
