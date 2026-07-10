namespace WarHub.CatalogStore.Reconcile;

/// <summary>
/// Per-catalog hooks the generic reconciler needs to identify, match, merge,
/// and stamp records. Implementations are pure (no I/O).
/// </summary>
public interface ICatalogRecordAdapter<T>
{
    /// <summary>Normalized identity, unique within a single reconciled set (a faction file).</summary>
    string IdentityKey(T record);

    /// <summary>Canonical source URL, used as the rename-detection fallback. Null if none.</summary>
    string? Url(T record);

    /// <summary>Merge a re-scraped record into the archived one: update-present, keep-on-empty. Preserves identity + firstSeen.</summary>
    T Merge(T existing, T fresh);

    /// <summary>Stamp the write-once firstSeen date.</summary>
    T WithFirstSeen(T record, string isoDate);

    /// <summary>True if the record already carries a firstSeen date.</summary>
    bool HasFirstSeen(T record);

    /// <summary>Apply a rename: keep existing identity + firstSeen, adopt fresh's name and mutable fields.</summary>
    T ApplyRename(T existing, T fresh);
}
