using WarHub.CatalogStore;
using WarHub.PaintCatalog.Tool.Models;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace WarHub.PaintCatalog.Tool.Enrichment;

/// <summary>
/// Applies the hand-maintained overrides file (<c>data/paints/overrides.yaml</c>).
///
/// The file has brand-slug keys at the ROOT carrying per-paint field overrides
/// (<c>{brand-slug}</c> → <c>{Name}|{Set}</c> → fields), plus reserved top-level sections:
/// <c>additions</c> (this class), and <c>aliases</c>/<c>retract</c> (see PaintOverrideAliases).
///
/// Each section is read INDEPENDENTLY: the document is parsed once into an untyped tree and only
/// the requested node is bound to a typed shape. That matters because the sections have different
/// shapes — before this, one <c>retract:</c> list anywhere in the file made the whole typed parse
/// throw and silently disabled EVERY field override in the file.
/// </summary>
public static class OverrideApplier
{
    /// <summary>Top-level keys that are sections, not brand slugs.</summary>
    internal static readonly IReadOnlySet<string> ReservedSections =
        new HashSet<string>(StringComparer.Ordinal) { "additions", "aliases", "retract" };

    private static readonly IDeserializer YamlDeserializer = new DeserializerBuilder()
        .WithNamingConvention(CamelCaseNamingConvention.Instance)
        .IgnoreUnmatchedProperties()
        .Build();

    // Used to re-emit ONE parsed node so it can be bound to a typed shape (see Bind). The shared
    // catalog serializer is deliberate: its QuotingEventEmitter keeps a scalar like the EAN
    // '0011921153770' or the code '0605' a quoted STRING across the round trip, instead of letting
    // it re-emit plain and come back as an integer with its leading zeros eaten.
    private static readonly ISerializer NodeSerializer = CatalogSerializer.CreateSerializer();

    /// <summary>
    /// Loads overrides from a YAML file and applies them to the paint list.
    /// Override key format: "{brand-slug}" → "{Name}|{Set}" → override fields.
    /// When hex is overridden, R/G/B are recomputed to stay in sync.
    /// </summary>
    public static IReadOnlyList<Paint> Apply(IReadOnlyList<Paint> paints, string brandSlug, string? overridesPath)
    {
        if (ReservedSections.Contains(brandSlug))
            return paints;

        Dictionary<string, PaintOverride>? brandOverrides =
            Bind<Dictionary<string, PaintOverride>>(LoadRoot(overridesPath), brandSlug);
        if (brandOverrides is null)
            return paints;

        return paints.Select(p =>
        {
            string key = $"{p.Name}|{p.Set}";
            if (!brandOverrides.TryGetValue(key, out PaintOverride? over) || over is null)
                return p;

            bool colourless = (over.Colourless ?? p.Colourless) == true;
            // A role outside the closed vocabulary is a typo in a hand-edited file, and a typo
            // that silently published would be worse than a run that stopped: fail loudly here.
            if (over.Role is not null && !RoleClassifier.Vocabulary.Contains(over.Role))
            {
                throw new InvalidOperationException(
                    $"overrides.yaml {brandSlug} '{key}': role '{over.Role}' is not in the vocabulary "
                    + $"({string.Join(", ", RoleClassifier.Roles)})");
            }
            string newHex = over.Hex ?? p.Hex;
            int newR = p.R;
            int newG = p.G;
            int newB = p.B;

            // When hex is overridden, recompute RGB to keep them in sync
            if (over.Hex is not null && TryParseHex(over.Hex, out int r, out int g, out int b))
            {
                newR = r;
                newG = g;
                newB = b;
            }

            // The one path that can say "this is sold by WEIGHT, not by volume". It has to be a
            // fold and not a coalesce: `over.VolumeMl ?? p.VolumeMl` cannot express a clear (an
            // absent key and an explicit `volumeMl: null` are the same thing to YamlDotNet on an
            // `int?`), and VolumeEnricher has already written the table's guess into `p` by the
            // time this runs, so a weight assertion sitting beside it would publish `weightG: 250`
            // next to a still-wrong `volumeMl: 17`. See NetContents for the rule and for why the
            // container travels with it.
            NetContents.Claim contents = NetContents.Merge(
                new NetContents.Claim(over.VolumeMl, over.WeightG, over.Packaging),
                new NetContents.Claim(p.VolumeMl, p.WeightG, p.Packaging));

            return p with
            {
                // Name/Set move the record's IDENTITY, so they land here rather than in the
                // reconciler -- see PaintOverride.Name. Every enrichment keyed on `{Name}|{Set}`
                // has ALREADY run by this point (BarcodeEnricher :245, ApplyEnrichment :249,
                // SwatchApplier :253 in PaintCatalogApp), which is deliberate and is the half of
                // the contract a renaming block has to honour: those files must key the paint by
                // the name the BASE emits, never the corrected one.
                Name = over.Name ?? p.Name,
                Set = over.Set ?? p.Set,
                ProductCode = over.ProductCode ?? p.ProductCode,
                // COLOURLESS CLEARS THE COLOUR, and does it here rather than at the call sites.
                // The assertion and its consequence cannot be separated: a varnish that keeps a
                // #FFFFFF stand-in is still a node in the equivalence graph no matter what the
                // flag says. Doing it in this step also undoes any fill SwatchApplier made at
                // PaintCatalogApp.cs:253, which runs BEFORE this one and cannot see the override.
                // An explicit `hex:` in the same block would be contradictory, so it loses.
                Hex = colourless ? "" : newHex,
                R = colourless ? 0 : newR,
                G = colourless ? 0 : newG,
                B = colourless ? 0 : newB,
                Colourless = over.Colourless ?? p.Colourless,
                // The classifier has already run (PaintCatalogApp enrichment chain), so this is
                // the per-record last word over it. RoleInvariant checks the pair afterwards.
                Role = over.Role ?? p.Role,
                VolumeMl = contents.VolumeMl,
                WeightG = contents.WeightG,
                Packaging = contents.Container,
                Ean = over.Ean ?? p.Ean,
                // Non-destructive: an override that supplies a NEW primary keeps the barcode it
                // displaced (plus any the override itself lists) instead of dropping it.
                AdditionalEans = BarcodeSet.Union(over.Ean ?? p.Ean, p.AdditionalEans, over.AdditionalEans, [p.Ean]),
                // Authoritative in BOTH directions, like every other field here: `bool?` makes an
                // explicit `false` distinguishable from an absent key, so writing one is a
                // deliberate statement that the source is wrong, not an accident.
                IsDiscontinued = over.IsDiscontinued ?? p.IsDiscontinued,
                // Same bool? discipline as IsDiscontinued above, and for the same reason: an
                // explicit `false` ("a source says this is set-exclusive") must stay
                // distinguishable from an absent key ("nobody said").
                SoldSeparately = over.SoldSeparately ?? p.SoldSeparately,
                PriceGbp = over.PriceGbp ?? p.PriceGbp,
                PriceUsd = over.PriceUsd ?? p.PriceUsd,
                PriceEur = over.PriceEur ?? p.PriceEur,
                PriceCad = over.PriceCad ?? p.PriceCad,
                SupersededBy = Blank(over.SupersededBy) ?? p.SupersededBy,
            };
        }).ToList();
    }

    /// <summary>
    /// Appends MINTED paints from the overrides file's <c>additions</c> section — records a
    /// maintainer researched that no upstream source supplies at all (a range move, a
    /// reformulation), as opposed to <c>data/paints/harvest/*.yaml</c> additions, which are
    /// GENERATED from observed manufacturer-catalog listings and are overwritten wholesale by the
    /// next generator run.
    ///
    /// Shape (mirrors the harvest additions it sits beside):
    /// <code>
    /// additions:
    ///   citadel-colour:
    ///     - name: Hexwraith Flame
    ///       set: Contrast
    ///       productCode: '99189960060'
    /// </code>
    ///
    /// Called at the same point in the pipeline as the harvest additions — BEFORE the enrichment
    /// chain — so a minted paint picks up volume/container/type/finish/barcodes from the same
    /// tables a native paint does, and the field-override section below still gets the last word.
    /// A minted paint carries no colour (<c>hex: ""</c>, R/G/B 0) exactly like a harvest addition:
    /// the swatch-extraction pass or an explicit hex override fills it later.
    /// Idempotent on <c>{Name}|{Set}|{ProductCode}</c>, so it is a no-op once upstream catches up.
    /// </summary>
    public static IReadOnlyList<Paint> AppendAdditions(
        IReadOnlyList<Paint> paints, string brandSlug, string? overridesPath)
    {
        Dictionary<string, object?>? root = LoadRoot(overridesPath);
        var additions = Bind<Dictionary<string, List<PaintAddition>>>(root, "additions");
        if (additions is null ||
            !additions.TryGetValue(brandSlug, out List<PaintAddition>? brandAdditions) ||
            brandAdditions is not { Count: > 0 })
        {
            return paints;
        }

        var existing = new HashSet<string>(
            paints.Select(p => $"{p.Name}|{p.Set}|{p.ProductCode}"), StringComparer.OrdinalIgnoreCase);

        List<Paint> result = paints.ToList();
        foreach (PaintAddition addition in brandAdditions)
        {
            if (addition is null || Blank(addition.Name) is null || Blank(addition.Set) is null)
                continue;
            string code = Blank(addition.ProductCode) ?? "";
            if (!existing.Add($"{addition.Name}|{addition.Set}|{code}"))
                continue;

            result.Add(new Paint
            {
                Name = addition.Name!,
                Set = addition.Set!,
                ProductCode = Blank(addition.ProductCode),
                R = 0,
                G = 0,
                B = 0,
                Hex = "",
                Ean = Blank(addition.Ean),
                ImageUrl = Blank(addition.ImageUrl),
                SupersededBy = Blank(addition.SupersededBy),
                SoldSeparately = addition.SoldSeparately,
            });
        }

        return result;
    }

    /// <summary>
    /// Materializes the REVERSE of every <c>supersededBy</c> declaration: the replacement paint's
    /// <c>supersedes</c> list. Only one direction is ever declared, so the two cannot drift apart —
    /// the same discipline the product side gets from a single <c>matches.supersessions</c> map.
    /// Runs after the field overrides, over one brand's finished list. A declaration whose target
    /// is not in this brand is left on the record as declared but produces no reverse link (and the
    /// publisher will not publish an unresolvable one).
    /// </summary>
    public static IReadOnlyList<Paint> LinkSupersessions(IReadOnlyList<Paint> paints)
    {
        var predecessors = new Dictionary<string, SortedSet<string>>(StringComparer.OrdinalIgnoreCase);
        foreach (Paint p in paints)
        {
            string? target = Blank(p.SupersededBy);
            string self = $"{p.Name}|{p.Set}";
            if (target is null || string.Equals(target, self, StringComparison.OrdinalIgnoreCase))
                continue;
            if (!predecessors.TryGetValue(target, out SortedSet<string>? set))
                predecessors[target] = set = new SortedSet<string>(StringComparer.Ordinal);
            set.Add(self);
        }

        if (predecessors.Count == 0)
            return paints;

        return paints
            .Select(p => predecessors.TryGetValue($"{p.Name}|{p.Set}", out SortedSet<string>? found)
                ? p with { Supersedes = found.ToList() }
                : p)
            .ToList();
    }

    internal static bool TryParseHex(string hex, out int r, out int g, out int b)
    {
        r = g = b = 0;
        string value = hex.StartsWith('#') ? hex[1..] : hex;
        if (value.Length != 6) return false;

        if (int.TryParse(value[0..2], System.Globalization.NumberStyles.HexNumber, null, out r) &&
            int.TryParse(value[2..4], System.Globalization.NumberStyles.HexNumber, null, out g) &&
            int.TryParse(value[4..6], System.Globalization.NumberStyles.HexNumber, null, out b))
        {
            return true;
        }

        r = g = b = 0;
        return false;
    }

    /// <summary>Parses the whole file into an untyped tree; null when absent or malformed.</summary>
    private static Dictionary<string, object?>? LoadRoot(string? overridesPath)
    {
        if (string.IsNullOrEmpty(overridesPath) || !File.Exists(overridesPath))
            return null;
        try
        {
            return YamlDeserializer.Deserialize<Dictionary<string, object?>>(File.ReadAllText(overridesPath));
        }
        catch
        {
            return null;
        }
    }

    /// <summary>
    /// Binds ONE top-level node to a typed shape. A section that fails to bind yields null and
    /// leaves every other section readable — the file is hand-edited, and one mistyped section
    /// must not take the rest of it down with it.
    /// </summary>
    private static T? Bind<T>(Dictionary<string, object?>? root, string key) where T : class
    {
        if (root is null || !root.TryGetValue(key, out object? node) || node is null)
            return null;
        try
        {
            return YamlDeserializer.Deserialize<T>(NodeSerializer.Serialize(node));
        }
        catch
        {
            return null;
        }
    }

    private static string? Blank(string? value) => string.IsNullOrWhiteSpace(value) ? null : value;
}

/// <summary>
/// Override entry for a single paint. Null fields are not overridden.
/// </summary>
public record PaintOverride
{
    /// <summary>
    /// States that this product has no colour -- see <see cref="Models.PaintRecord.Colourless"/>.
    /// Writing it also CLEARS the record's hex and R/G/B, so it is the one override that removes
    /// data rather than supplying it; that is deliberate, because the stand-in greys it removes
    /// are what put mediums and varnishes into the colour-equivalence graph.
    /// </summary>
    public bool? Colourless { get; init; }

    /// <summary>
    /// States what this product is FOR -- see <see cref="Models.PaintRecord.Role"/> -- when the
    /// <see cref="RoleClassifier"/> gets it wrong for one record. Must be a slug from
    /// <see cref="RoleClassifier.Roles"/>; anything else fails the run. A varnish, medium or
    /// cleaner declared here still needs <see cref="Colourless"/> beside it, or
    /// <see cref="RoleInvariant"/> refuses the archive.
    /// </summary>
    public string? Role { get; init; }

    /// <summary>
    /// Corrected NAME, and with <see cref="Set"/> the last of the four identity components to get
    /// a pre-reconciliation rewrite. Identity is `set|name|productCode|hex`, and until now only
    /// productCode and hex could be moved here — so a base-sourced record whose upstream NAME was
    /// wrong could not be corrected at all. Not for want of a rule: `aliases:` stitches a rename
    /// to its old record, but only if the old identity key is VACATED, and
    /// <see cref="CatalogReconciler"/> seeds `consumed` with every key the fresh parse re-asserts
    /// (CatalogReconciler.cs:38-46). The base re-asserts the misspelled name every run, so the
    /// alias was refused and the run minted a duplicate with today's firstSeen instead.
    ///
    /// Writing it here fixes that the same way the army-painter `Brainmatter Beige` code
    /// correction already does: <see cref="Apply"/> runs at PaintCatalogApp.cs:256, BEFORE
    /// reconciliation, so the old key is never asserted and the paired `aliases:` entry fires.
    /// A rename therefore still REQUIRES its alias — without one the reconciler sees an unknown
    /// key, mints, and strands the original.
    ///
    /// THE LOOKUP KEY IS THE OLD NAME AND STAYS THAT WAY. <see cref="Apply"/> matches on
    /// `{Name}|{Set}` as the BASE emits it, so a block that renames must keep the misspelling as
    /// its own key forever; "tidying" it to the corrected name silently disables the correction.
    /// </summary>
    public string? Name { get; init; }

    /// <summary>Corrected SET. Same mechanism and same alias requirement as <see cref="Name"/>.</summary>
    public string? Set { get; init; }

    public string? ProductCode { get; init; }
    public string? Hex { get; init; }
    public int? VolumeMl { get; init; }
    /// <summary>
    /// NET CONTENTS in grams — and the only mechanism in the pipeline that can retire a volume.
    /// Writing it is a statement that this product is measured by mass, so
    /// <see cref="NetContents.Merge"/> drops <see cref="VolumeMl"/> and <see cref="Packaging"/>
    /// rather than leaving the record claiming both (see that class for why the coalesce every
    /// other field here uses cannot do the job). Like <see cref="AdditionalEans"/> and the prices,
    /// this is ALSO the read shape of the generated barcode bridge, so the property must exist
    /// here or a `weightG` in that file is silently dropped by IgnoreUnmatchedProperties.
    /// </summary>
    public int? WeightG { get; init; }
    public string? Packaging { get; init; }
    /// <summary>See PaintRecord.SoldSeparately. `false` states set-exclusivity; null is unstated.</summary>
    public bool? SoldSeparately { get; init; }
    public string? Ean { get; init; }
    /// <summary>
    /// Extra barcodes for this paint. Also the read shape for the generated barcodes file
    /// (BarcodeEnricher deserializes into this type), which is why the property must exist here or
    /// `additionalEans` is silently discarded by IgnoreUnmatchedProperties at parse time.
    /// </summary>
    public List<string>? AdditionalEans { get; init; }

    /// <summary>
    /// Marks a paint the manufacturer no longer sells, which drives `status: discontinued` and
    /// `availability: out_of_stock` via PaintRecordMapper. It exists as an override because
    /// discontinuation is an ABSENCE -- the upstream source simply stops listing a paint, and the
    /// manufacturer bridge is built from trade rows that by definition no longer contain it, so
    /// neither can assert it. A researched, cited decision recorded as data is the honest shape.
    /// </summary>
    public bool? IsDiscontinued { get; init; }
    /// <summary>
    /// Manufacturer list price. Like <see cref="AdditionalEans"/> these are ALSO the read shape for
    /// the generated manufacturer bridge file, so the bridge can carry trade prices. Availability
    /// deliberately does not travel with them: trade evidence carries no stock signal, and one
    /// paint identity spans several retail SKUs whose stock differs.
    /// </summary>
    public decimal? PriceGbp { get; init; }
    public decimal? PriceUsd { get; init; }
    public decimal? PriceEur { get; init; }
    public decimal? PriceCad { get; init; }
    /// <summary>
    /// <c>{Name}|{Set}</c> of the paint that replaced this one. The ONE declared lineage direction;
    /// the reverse (`supersedes`) is derived by <see cref="OverrideApplier.LinkSupersessions"/>.
    /// </summary>
    public string? SupersededBy { get; init; }
}

/// <summary>A minted paint from the overrides file's <c>additions</c> section.</summary>
public record PaintAddition
{
    /// <summary>See PaintRecord.SoldSeparately. Written only when a source states it.</summary>
    public bool? SoldSeparately { get; init; }
    public string? Name { get; init; }
    public string? Set { get; init; }
    public string? ProductCode { get; init; }
    public string? Ean { get; init; }
    public string? ImageUrl { get; init; }
    public string? SupersededBy { get; init; }
    /// <summary>Provenance for the human reader; not consumed by the pipeline.</summary>
    public string? Source { get; init; }
    public string? SourceUrl { get; init; }
}

/// <summary>Barcode-set helpers shared by the enrichers and the reconciler.</summary>
public static class BarcodeSet
{
    /// <summary>
    /// Every extra barcode, deduped and ordinal-sorted, with the primary removed and blanks
    /// dropped. Returns null (never an empty list) so the key is omitted from YAML/JSON rather
    /// than churning every archive file with `additionalEans: []`.
    /// </summary>
    public static List<string>? Union(string? primary, params IEnumerable<string?>?[] sources)
    {
        var set = new SortedSet<string>(StringComparer.Ordinal);
        foreach (IEnumerable<string?>? source in sources)
        {
            if (source is null) continue;
            foreach (string? value in source)
            {
                string trimmed = value?.Trim() ?? "";
                if (trimmed.Length > 0 && !string.Equals(trimmed, primary?.Trim(), StringComparison.Ordinal))
                    set.Add(trimmed);
            }
        }
        return set.Count > 0 ? set.ToList() : null;
    }
}
