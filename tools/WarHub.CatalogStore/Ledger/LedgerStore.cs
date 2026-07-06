namespace WarHub.CatalogStore.Ledger;

/// <summary>Loads and saves the liveness ledger sidecar file.</summary>
public static class LedgerStore
{
    public static async Task<LivenessLedger> LoadAsync(string path, CancellationToken ct = default)
    {
        if (!File.Exists(path))
            return new LivenessLedger();

        string yaml = await File.ReadAllTextAsync(path, ct);
        LivenessLedger? ledger = CatalogSerializer.CreateDeserializer().Deserialize<LivenessLedger>(yaml);
        return ledger ?? new LivenessLedger();
    }

    public static async Task SaveAsync(string path, LivenessLedger ledger, CancellationToken ct = default)
    {
        string? dir = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(dir))
            Directory.CreateDirectory(dir);

        string yaml = CatalogSerializer.CreateSerializer().Serialize(ledger);
        await File.WriteAllTextAsync(path, yaml, ct);
    }
}
