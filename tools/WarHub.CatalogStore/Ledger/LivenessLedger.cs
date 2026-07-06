namespace WarHub.CatalogStore.Ledger;

/// <summary>
/// Volatile per-run liveness state, kept in a single sidecar file per catalog
/// so the data files stay churn-free. All dates are ISO yyyy-MM-dd strings.
/// </summary>
public sealed record LivenessLedger
{
    public int SchemaVersion { get; init; } = 1;
    public Dictionary<string, LedgerSource> Sources { get; init; } = new();
    public Dictionary<string, LedgerRecord> Records { get; init; } = new();
}

/// <summary>Per-source scrape health, keyed by source slug (e.g. manufacturer slug).</summary>
public sealed record LedgerSource
{
    public string? LastRun { get; init; }
    public string? LastGoodRun { get; init; }
    public bool LastRunSucceeded { get; init; }
    public int ProductCount { get; init; }
}

/// <summary>Per-record liveness, keyed by the record's full path identity key.</summary>
public sealed record LedgerRecord
{
    public required string LastSeen { get; init; }
    public int MissStreak { get; init; }
}
