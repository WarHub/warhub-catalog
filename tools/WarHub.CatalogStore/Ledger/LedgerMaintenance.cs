namespace WarHub.CatalogStore.Ledger;

/// <summary>
/// Shared, pure ledger-maintenance helpers: a source-health guard against
/// implausible scrape drops, and orphan garbage-collection for the liveness
/// ledger's per-record entries.
/// </summary>
public static class LedgerMaintenance
{
    /// <summary>True when a source's fresh count dropped implausibly vs its last-good count,
    /// signalling a partial/garbled scrape. No prior (priorCount &lt;= 0) ⇒ never implausible.</summary>
    public static bool IsImplausibleDrop(int priorCount, int scrapedCount, double fraction = 0.5)
        => priorCount > 0 && scrapedCount < priorCount * fraction;

    /// <summary>Removes ledger records under the given healthy-and-fully-scraped sources whose keys
    /// are not in <paramref name="liveKeys"/>. Records under any other source are untouched.
    /// Returns the removed keys.</summary>
    /// <remarks>
    /// Mutates the passed-in <paramref name="ledger"/> in place (removes entries from its
    /// <c>Records</c> dictionary), mirroring <see cref="LivenessUpdater.Apply"/>'s convention.
    /// </remarks>
    public static IReadOnlyList<string> PruneOrphans(
        LivenessLedger ledger, IReadOnlySet<string> liveKeys, IReadOnlySet<string> prunableSources)
    {
        var removed = new List<string>();

        foreach (string key in ledger.Records.Keys.ToList())
        {
            int slashIndex = key.IndexOf('/');
            if (slashIndex < 0)
                continue;

            string sourceSegment = key[..slashIndex];
            if (!prunableSources.Contains(sourceSegment))
                continue;

            if (liveKeys.Contains(key))
                continue;

            ledger.Records.Remove(key);
            removed.Add(key);
        }

        return removed;
    }
}
