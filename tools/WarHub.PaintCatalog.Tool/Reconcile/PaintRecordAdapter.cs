using WarHub.CatalogStore;
using WarHub.CatalogStore.Reconcile;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Reconcile;

/// <summary>Adapts <see cref="PaintRecord"/> to the generic reconciler.</summary>
public sealed class PaintRecordAdapter : ICatalogRecordAdapter<PaintRecord>
{
    public string IdentityKey(PaintRecord r) => string.Join('|',
        NameNormalizer.Normalize(r.Details.Set),
        NameNormalizer.Normalize(r.Name),
        NameNormalizer.Normalize(r.ProductCode ?? ""),
        NameNormalizer.Normalize(r.Details.Hex));

    // Composite key is strong; product codes / image URLs are non-unique/empty in paint data,
    // so URL-based rename detection is disabled. Genuine renames use aliases: overrides.
    public string? Url(PaintRecord r) => null;

    public PaintRecord Merge(PaintRecord existing, PaintRecord fresh)
    {
        // THE ARCHIVE MUST BE ABLE TO FORGET A VOLUME. Until 2026-08-06 this block was
        // `VolumeMl = fresh ?? existing` plus `Pick` on the container, so a value once committed
        // could never be withdrawn -- and the two Green Stuff World tubs measured in grams would
        // have kept re-inheriting the `volumeMl: 17` already on disk even after every upstream
        // writer stopped producing it. NetContents makes a stated mass replace the pair, in
        // exactly the same shape it does in OverrideApplier, so the two cannot drift.
        NetContents.Claim contents = NetContents.Merge(
            new NetContents.Claim(fresh.Details.VolumeMl, fresh.Details.WeightG, fresh.Details.Container),
            new NetContents.Claim(existing.Details.VolumeMl, existing.Details.WeightG, existing.Details.Container));

        return existing with
        {
            // Name, FirstSeen, Category, and the identity components (Set/Hex/ProductCode) are immutable.
            Status = fresh.Status is "discontinued" or "delisted" ? fresh.Status : existing.Status,
            Availability = Pick(fresh.Availability, existing.Availability) ?? "unknown",
            Ean = Pick(fresh.Ean, existing.Ean),
            // Non-destructive re-barcoding. EAN is not part of the identity key (set|name|productCode|
            // hex), so a fresh harvest carrying a DIFFERENT barcode lands on this same record and
            // `Pick` hands the primary slot to fresh -- which previously destroyed the stored barcode
            // outright. Keep it: a paint bought years ago must stay resolvable by the barcode on the
            // pot the owner actually has.
            AdditionalEans = Enrichment.BarcodeSet.Union(
                Pick(fresh.Ean, existing.Ean), existing.AdditionalEans, fresh.AdditionalEans, [existing.Ean])
                is { Count: > 0 } merged ? [.. merged] : null,
            ImageUrl = Pick(fresh.ImageUrl, existing.ImageUrl),
            // Price is EVIDENCE (trade bridge / hand override), so it behaves like Ean and ImageUrl:
            // a fresh figure wins, a run that simply carries no price keeps the last known one rather
            // than blanking a record because this run's bridge did not quote it.
            PriceGbp = fresh.PriceGbp ?? existing.PriceGbp,
            PriceUsd = fresh.PriceUsd ?? existing.PriceUsd,
            PriceEur = fresh.PriceEur ?? existing.PriceEur,
            PriceCad = fresh.PriceCad ?? existing.PriceCad,
            // Lineage and set-exclusivity are DECLARATIONS (overrides.yaml), not evidence: fresh is
            // authoritative in both directions, INCLUDING clearing. Withdrawing the declaration must
            // actually withdraw the link -- mirroring the product side, where the resolver recomputes
            // it from matches.yaml every run. Records absent from `fresh` never reach Merge, so
            // nothing else can be cleared.
            Supersedes = fresh.Supersedes,
            SupersededBy = fresh.SupersededBy,
            // `soldSeparately` was MISSING from this with-list until 2026-08-11, so the declaration
            // could only ever land on the INSERT path -- the one run that mints a brand-new record.
            // A pot already in the archive could never GAIN it (existing `null` won), and one that
            // had it could never LOSE it. AK17082 carries `false` today only because that was the
            // run that created it. Note this is a BARE assignment and not `fresh ?? existing`: the
            // tri-state's `false` is a claim a named source made in words, so deleting the source
            // has to restore `null` ("no source said"), exactly as for the two lines above. Coalesce
            // here and withdrawal becomes impossible in the other direction instead.
            SoldSeparately = fresh.SoldSeparately,
            Details = existing.Details with
            {
                VolumeMl = contents.VolumeMl,
                WeightG = contents.WeightG,
                Container = contents.Container,
                Type = Pick(fresh.Details.Type, existing.Details.Type),
                Finish = Pick(fresh.Details.Finish, existing.Details.Finish),
            },
        };
    }

    public PaintRecord WithFirstSeen(PaintRecord r, string isoDate) => r with { FirstSeen = isoDate };

    public bool HasFirstSeen(PaintRecord r) => !string.IsNullOrWhiteSpace(r.FirstSeen);

    // A rename/alias moves the record to FRESH's identity — the stored record must carry the
    // identity fields its new key was computed from, or the key and the record disagree and
    // the alias has to fire again every run forever. For a pure name rename these assignments
    // are no-ops (identity fields matched); for a colour backfill (empty-hex archive record
    // aliased to its hex-carrying fresh twin — see the auto-alias pass in PaintCatalogApp)
    // they are what actually lands the colour. History (FirstSeen, status, availability
    // backfills) still comes from `existing` via Merge, and the declarations (lineage,
    // soldSeparately) from `fresh` via that same call -- an aliased record needs no separate
    // handling here precisely because every field decision is made once, in Merge.
    public PaintRecord ApplyRename(PaintRecord existing, PaintRecord fresh)
    {
        PaintRecord merged = Merge(existing, fresh);
        return merged with
        {
            Name = fresh.Name,
            ProductCode = fresh.ProductCode,
            Details = merged.Details with
            {
                Set = fresh.Details.Set,
                Hex = fresh.Details.Hex,
                R = fresh.Details.R,
                G = fresh.Details.G,
                B = fresh.Details.B,
            },
        };
    }

    private static string? Pick(string? fresh, string? existing) =>
        string.IsNullOrWhiteSpace(fresh) ? existing : fresh;
}
