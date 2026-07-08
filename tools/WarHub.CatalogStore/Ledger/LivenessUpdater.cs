namespace WarHub.CatalogStore.Ledger;

/// <summary>Result of applying one source's scrape outcome to the ledger.</summary>
public sealed record LivenessUpdate(
    LivenessLedger Ledger,
    IReadOnlySet<string> Flagged,
    IReadOnlySet<string> Reactivated);

/// <summary>
/// Applies a single source's scrape outcome to the ledger: updates per-source
/// health, resets/increments per-record miss streaks (gated on source success),
/// and computes which records cross the auto-flag threshold or reactivate.
/// </summary>
public static class LivenessUpdater
{
    /// <remarks>
    /// Mutates the passed-in <paramref name="ledger"/> in place (writes into
    /// its <c>Sources</c>/<c>Records</c> dictionaries) and returns that same
    /// instance via <see cref="LivenessUpdate.Ledger"/> for convenience chaining.
    /// </remarks>
    public static LivenessUpdate Apply(
        LivenessLedger ledger,
        string sourceKey,
        bool sourceSucceeded,
        int scrapedCount,
        IReadOnlySet<string> seenKeys,
        IReadOnlyCollection<string> knownKeysForSource,
        string today,
        int missThreshold = 3,
        IReadOnlySet<string>? currentlyFlaggedKeys = null)
    {
        currentlyFlaggedKeys ??= new HashSet<string>();
        var flagged = new HashSet<string>();
        var reactivated = new HashSet<string>();

        LedgerSource prior = ledger.Sources.GetValueOrDefault(sourceKey) ?? new LedgerSource();

        if (!sourceSucceeded)
        {
            ledger.Sources[sourceKey] = prior with
            {
                LastRun = today,
                LastRunSucceeded = false,
            };
            return new LivenessUpdate(ledger, flagged, reactivated);
        }

        ledger.Sources[sourceKey] = prior with
        {
            LastRun = today,
            LastGoodRun = today,
            LastRunSucceeded = true,
            ProductCount = scrapedCount,
        };

        // Seen records: reset streak, stamp last-seen, reactivate if previously flagged.
        foreach (string key in seenKeys)
        {
            ledger.Records[key] = new LedgerRecord { LastSeen = today, MissStreak = 0 };
            if (currentlyFlaggedKeys.Contains(key))
                reactivated.Add(key);
        }

        // Known-but-unseen records: increment streak; flag on crossing the threshold.
        // Distinct() guards against a duplicate key double-incrementing its miss streak.
        foreach (string key in knownKeysForSource.Distinct())
        {
            if (seenKeys.Contains(key))
                continue;

            LedgerRecord prev = ledger.Records.GetValueOrDefault(key)
                ?? new LedgerRecord { LastSeen = today, MissStreak = 0 };
            int newStreak = prev.MissStreak + 1;
            ledger.Records[key] = prev with { MissStreak = newStreak };

            if (newStreak == missThreshold)
                flagged.Add(key);
        }

        return new LivenessUpdate(ledger, flagged, reactivated);
    }
}
