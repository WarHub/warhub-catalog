namespace WarHub.PaintCatalog.Tool.Models;

/// <summary>
/// How much of the product is in the pot, and what the pot is: <c>volumeMl</c> OR <c>weightG</c>,
/// plus the <c>container</c> that was asserted alongside. One rule, stated once, because FIVE write
/// sites merge this triple (<see cref="Enrichment.VolumeEnricher"/>,
/// <see cref="Enrichment.BarcodeEnricher"/>, <see cref="Enrichment.OverrideApplier"/>,
/// <see cref="Reconcile.PaintRecordAdapter"/>, and the Scalemates scraped-brand default in
/// PaintCatalogApp -- that fifth one was missed on the first pass and found in review)
/// and before this they each open-coded a bare
/// <c>incoming ?? current</c>. That coalesce is why adding <c>weightG</c> on its own would have
/// changed NOTHING visible: measured 2026-08-06, both weight-sold paint records carry a committed
/// `volumeMl: 17` written by VolumeTable's brand-wide Green Stuff World row, and a `??` at any of
/// the five sites re-supplies it forever. The field is the small half of the job; this is the
/// other half.
///
/// THE RULE: a net-contents claim is ATOMIC. Whoever states one states the whole of it, so a
/// weight assertion CLEARS the volume rather than sitting beside it, and a volume assertion clears
/// any stored mass. The alternative -- an explicit `clearVolumeMl: true` flag, or a sentinel -- was
/// rejected because YamlDotNet cannot distinguish an absent key from an explicit `volumeMl: null`
/// on an `int?`, so "clear" would have needed its own vocabulary in overrides.yaml AND in the
/// generated bridge that shares <see cref="Enrichment.PaintOverride"/> as its read shape. Stating
/// a mass IS the clear, and it carries its own evidence.
///
/// WHY THE CONTAINER TRAVELS WITH IT. `container` is not net contents, but on today's data it is
/// wrong for exactly the same reason and from exactly the same line: VolumeTable's rule writes the
/// volume and the packaging as one unconditional pair (VolumeEnricher), so the two 250 g Green
/// Stuff World tubs inherited `container: dropper` from the same brand-wide row that gave them
/// `volumeMl: 17`. The committed vocabulary is exactly dropper / jar / pot / tin / spray (plus a
/// null for records that state none) across the brand files, measured 2026-08-06. Re-derive from
/// data/paints/brands/*.yaml (`details.container`) -- none of which
/// describes a tub, so `null` ("we have no word for it") is the only honest value and is strictly
/// better than `dropper` ("it is a dropper bottle", false). A volume claim does NOT clear the
/// container the same way: an incoming volume with no container is common (a bridge row, a
/// per-record override) and must keep the container the table already established.
///
/// <c>weightG</c> IS NET CONTENTS, NOT SHIPPING WEIGHT. `hints.grams` exists on evidence
/// observations across multiple sources and is
/// Shopify's `variant.grams` GROSS weight: a paintbrush is 3 g, an 18 ml dropper 26-31 g, a paint
/// case 2450 g. gen_paint_harvest.py:82 already depends on it meaning that. Wiring it here would
/// fabricate net contents on far too many records to fix just a couple. Nothing may feed <c>WeightG</c> that is not a
/// stated net content.
///
/// <c>weightG</c> IS IN NO IDENTITY KEY, verified 2026-08-06: PaintRecordAdapter.IdentityKey is
/// set|name|productCode|hex (:10-14) and PaintBuilder's NaturalKey is
/// brandSlug|name|set|code|hex (:20-21). That is exactly why a SIBLING field is safe here where
/// repurposing <c>volumeMl</c> into a unit-plus-amount pair would not be -- and it is the same
/// property BarcodeEnricher.cs:32-36 already relies on to justify overwriting a volume.
/// </summary>
public static class NetContents
{
    /// <summary>What one writer says about the pot. All three null = "this writer says nothing".</summary>
    public readonly record struct Claim(int? VolumeMl, int? WeightG, string? Container);

    /// <summary>
    /// Folds <paramref name="incoming"/> onto <paramref name="current"/>.
    ///
    /// IDENTITY ON TODAY'S DATA, and this is the guarantee that makes the change safe to ship: when
    /// no <c>WeightG</c> is present on either side -- all but two committed paint records,
    /// measured 2026-08-06 -- this reduces exactly to the `incoming ?? current` (volume) and `Pick`
    /// (container) the five sites open-coded before. See NetContentsTests, which asserts the
    /// reduction rather than restating it.
    /// </summary>
    public static Claim Merge(Claim incoming, Claim current)
    {
        // A stated MASS retires a volume the writer did NOT restate, and the container goes with
        // it -- because VolumeTable writes those two as a pair, so a wrong volume means the
        // container beside it was never observed either (both GSW tubs read `17 ml`/`dropper`
        // from one brand-wide row; they are 250 g tubs).
        //
        // BUT ONLY WHEN THE VOLUME IS ACTUALLY RETIRED. A claim stating BOTH a mass and a volume
        // is the pigment-in-a-jar case this field exists to allow -- two true facts about one pot
        // -- and there the vessel is still known, so the container must survive. Clearing it
        // unconditionally was a real defect: a couple of hundred committed pigment/powder/paste/sand
        // records carry both a volume and a container (29 of them exactly
        // `30 ml`/`jar`), and they are the most likely users of `weightG`. Every docstring on this
        // field advertises that case as safe, so the code had better make it so.
        if (incoming.WeightG is not null)
        {
            string? container = incoming.VolumeMl is not null
                ? Blank(incoming.Container) ?? Blank(current.Container)   // vessel still known
                : Blank(incoming.Container);                              // vessel retired with the volume
            return new Claim(incoming.VolumeMl, incoming.WeightG, container);
        }

        // A stated VOLUME retires any stored mass. Symmetric, so withdrawing a weight assertion
        // actually withdraws it instead of leaving a record claiming both -- the same discipline
        // PaintRecordAdapter.cs:54-59 applies to lineage. The container is NOT cleared here:
        // an incoming volume with no container is routine (a bridge row, a per-record override)
        // and must keep the one the table already established.
        if (incoming.VolumeMl is not null)
            return new Claim(incoming.VolumeMl, null, Blank(incoming.Container) ?? Blank(current.Container));

        // Says nothing about the amount; container still fills a blank, as `Pick` always did.
        return new Claim(current.VolumeMl, current.WeightG, Blank(incoming.Container) ?? Blank(current.Container));
    }

    private static string? Blank(string? value) => string.IsNullOrWhiteSpace(value) ? null : value;
}
