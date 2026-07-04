using System.Security.Cryptography;
using System.Text.Json;

namespace WarHub.Catalog.Publish;

/// <summary>
/// Serializes documents into the <c>dist/</c> tree, recording a <see cref="FileEntry"/>
/// (path, byte size, sha256) for the manifest as it goes. Validates each document
/// against its published JSON Schema before it is written.
/// </summary>
internal sealed class CatalogWriter(string distRoot, SchemaValidator validator)
{
    private readonly List<FileEntry> _files = [];

    public IReadOnlyList<FileEntry> Files => _files;

    public void Write(string relPath, string schemaName, string kind, string? partition, int? records, object document)
    {
        string json = JsonSerializer.Serialize(document, document.GetType(), JsonConfig.Options);
        validator.Validate(schemaName, json, relPath);

        string full = Path.Combine(distRoot, relPath.Replace('/', Path.DirectorySeparatorChar));
        Directory.CreateDirectory(Path.GetDirectoryName(full)!);
        File.WriteAllText(full, json);

        byte[] bytes = File.ReadAllBytes(full);
        string sha = Convert.ToHexStringLower(SHA256.HashData(bytes));
        _files.Add(new FileEntry(relPath, kind, partition, records, bytes.Length, sha));
    }

    /// <summary>Copies the authored JSON Schema files into <c>dist/schema/</c> and records them.</summary>
    public void CopySchemas(string schemaSourceDir)
    {
        foreach (string src in Directory.EnumerateFiles(schemaSourceDir, "*.json").OrderBy(f => f, StringComparer.Ordinal))
        {
            string name = Path.GetFileName(src);
            string relPath = $"schema/{name}";
            string full = Path.Combine(distRoot, "schema", name);
            Directory.CreateDirectory(Path.GetDirectoryName(full)!);
            File.Copy(src, full, overwrite: true);
            byte[] bytes = File.ReadAllBytes(full);
            string sha = Convert.ToHexStringLower(SHA256.HashData(bytes));
            _files.Add(new FileEntry(relPath, "schema", null, null, bytes.Length, sha));
        }
    }
}
