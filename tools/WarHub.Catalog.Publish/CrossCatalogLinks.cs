namespace WarHub.Catalog.Publish;

/// <summary>
/// The seam between the two catalogs this process publishes.
///
/// A product and a paint can be the same physical thing -- a Citadel pot is a SKU in the product
/// catalog AND a colour in the paint catalog -- and the only evidence tying them together is the
/// barcode printed on the pot. Nothing else matches: the names differ, the availability differs,
/// the ids come from different id spaces. So the barcode is the join key, and this type is the
/// only place that join is computed.
///
/// Two outputs, one pass:
///   * <see cref="BarcodeIndexDocument"/> (<c>dist/barcodes.json</c>) -- every barcode in either
///     catalog to the records carrying it, so a consumer with a scanner can resolve without
///     downloading both catalogs and building the index itself.
///   * <c>paintIds</c> / <c>productIds</c> on the records, so a consumer that already holds a
///     record does not need a second fetch.
///
/// Both are derived from the ids of THIS build. Paint ids carry positional <c>-N</c> suffixes
/// wherever a brand/name slug collides -- measured on real data, 1,541 of 8,520 paint records
/// (18.1%) across 1,046 collided slug groups -- and the position that decides <c>-2</c> from
/// <c>-3</c> is a sort over the upstream YAML, so those suffixes MOVE when the data moves. A
/// paint id is therefore stable within a release but NOT yet across releases. That is precisely
/// why the link is EMITTED rather than left for a consumer to assume: it is internally
/// consistent within one release, which is the strongest claim the current id scheme supports.
///
/// Matching is on the canonical barcode string exactly as published. No normalization is
/// invented here that the rest of the pipeline does not already do -- if two records disagree
/// about leading zeros or check digits, they do not match, and that is a data bug to fix
/// upstream, not to paper over at publish time.
/// </summary>
internal sealed class BarcodeIndex
{
    public const string ProductCatalog = "product";
    public const string PaintCatalog = "paint";

    private BarcodeIndex(
        IReadOnlyDictionary<string, IReadOnlyList<BarcodeRef>> barcodes,
        IReadOnlyDictionary<string, IReadOnlyList<string>> paintIdsByProductId,
        IReadOnlyDictionary<string, IReadOnlyList<string>> productIdsByPaintId,
        int productBarcodes,
        int paintBarcodes,
        int crossCatalog,
        int references)
    {
        Barcodes = barcodes;
        PaintIdsByProductId = paintIdsByProductId;
        ProductIdsByPaintId = productIdsByPaintId;
        ProductBarcodes = productBarcodes;
        PaintBarcodes = paintBarcodes;
        CrossCatalog = crossCatalog;
        References = references;
    }

    /// <summary>Barcode -> the records carrying it, both keys and values deterministically sorted.</summary>
    public IReadOnlyDictionary<string, IReadOnlyList<BarcodeRef>> Barcodes { get; }

    public IReadOnlyDictionary<string, IReadOnlyList<string>> PaintIdsByProductId { get; }
    public IReadOnlyDictionary<string, IReadOnlyList<string>> ProductIdsByPaintId { get; }

    /// <summary>Distinct barcodes across both catalogs.</summary>
    public int Total => Barcodes.Count;

    /// <summary>Barcodes carried by at least one product record.</summary>
    public int ProductBarcodes { get; }

    /// <summary>Barcodes carried by at least one paint record.</summary>
    public int PaintBarcodes { get; }

    /// <summary>
    /// Barcodes held by MORE THAN ONE CATALOG. The number this document exists to publish:
    /// before it, nothing in the pipeline even detected the overlap.
    /// </summary>
    public int CrossCatalog { get; }

    /// <summary>Total (barcode, record) pairs -- <see cref="Total"/> plus every extra holder.</summary>
    public int References { get; }

    private sealed class Holders
    {
        public List<string> Products { get; } = [];
        public List<string> Paints { get; } = [];
    }

    public static BarcodeIndex Build(IEnumerable<ProductRecord> products, IEnumerable<PaintRecord> paints)
    {
        var holders = new Dictionary<string, Holders>(StringComparer.Ordinal);

        foreach (ProductRecord p in products)
        {
            foreach (string code in BarcodesOf(p.Ean, p.AdditionalEans))
            {
                Holder(holders, code).Products.Add(p.Id);
            }
        }

        foreach (PaintRecord x in paints)
        {
            foreach (string code in BarcodesOf(x.Ean, x.AdditionalEans))
            {
                Holder(holders, code).Paints.Add(x.Id);
            }
        }

        var barcodes = new Dictionary<string, IReadOnlyList<BarcodeRef>>(holders.Count, StringComparer.Ordinal);
        var paintIdsByProductId = new Dictionary<string, SortedSet<string>>(StringComparer.Ordinal);
        var productIdsByPaintId = new Dictionary<string, SortedSet<string>>(StringComparer.Ordinal);
        int productBarcodes = 0, paintBarcodes = 0, crossCatalog = 0, references = 0;

        foreach (string code in holders.Keys.OrderBy(k => k, StringComparer.Ordinal))
        {
            Holders h = holders[code];
            // A barcode held by two records in the SAME catalog is the product resolver's
            // business (it adjudicates duplicate-barcode conflicts upstream); measured on real
            // data there are 2 such barcodes. Publish both holders and move on -- the index
            // reports what is there, it does not adjudicate and must not choke on it.
            barcodes[code] =
            [
                .. h.Products.Select(id => new BarcodeRef(ProductCatalog, id))
                    .Concat(h.Paints.Select(id => new BarcodeRef(PaintCatalog, id)))
                    .OrderBy(r => r.Catalog, StringComparer.Ordinal)
                    .ThenBy(r => r.Id, StringComparer.Ordinal),
            ];

            references += h.Products.Count + h.Paints.Count;
            if (h.Products.Count > 0)
            {
                productBarcodes++;
            }
            if (h.Paints.Count > 0)
            {
                paintBarcodes++;
            }
            if (h.Products.Count == 0 || h.Paints.Count == 0)
            {
                continue;
            }

            crossCatalog++;
            foreach (string productId in h.Products)
            {
                Links(paintIdsByProductId, productId).UnionWith(h.Paints);
            }
            foreach (string paintId in h.Paints)
            {
                Links(productIdsByPaintId, paintId).UnionWith(h.Products);
            }
        }

        return new BarcodeIndex(
            barcodes,
            Freeze(paintIdsByProductId),
            Freeze(productIdsByPaintId),
            productBarcodes,
            paintBarcodes,
            crossCatalog,
            references);
    }

    /// <summary>
    /// Stamps the computed links onto the assembled records. Runs between assemble and write
    /// because a link needs both catalogs in hand and neither document is on disk yet.
    /// </summary>
    public void ApplyTo(ProductAssembly products, PaintAssembly paints)
    {
        products.MapRecords(r =>
            PaintIdsByProductId.TryGetValue(r.Id, out IReadOnlyList<string>? ids) ? r with { PaintIds = ids } : r);
        paints.MapRecords(r =>
            ProductIdsByPaintId.TryGetValue(r.Id, out IReadOnlyList<string>? ids) ? r with { ProductIds = ids } : r);
    }

    public BarcodeIndexDocument ToDocument(Provenance prov, string relPath) => new()
    {
        Version = prov.Version,
        GeneratedAt = prov.GeneratedAt,
        GitCommit = prov.GitCommit,
        Counts = new Dictionary<string, int>
        {
            ["barcodes"] = Total,
            ["productBarcodes"] = ProductBarcodes,
            ["paintBarcodes"] = PaintBarcodes,
            ["crossCatalog"] = CrossCatalog,
            ["references"] = References,
        },
        Source = prov.SourceFor(relPath),
        Barcodes = Barcodes,
    };

    /// <summary>
    /// The barcodes one record carries, de-duplicated: a record that repeats its own primary
    /// barcode in <c>additionalEans</c> is one holder, not two.
    /// </summary>
    private static IEnumerable<string> BarcodesOf(string? primary, IReadOnlyList<string>? additional)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        if (!string.IsNullOrWhiteSpace(primary) && seen.Add(primary))
        {
            yield return primary;
        }
        foreach (string code in additional ?? [])
        {
            if (!string.IsNullOrWhiteSpace(code) && seen.Add(code))
            {
                yield return code;
            }
        }
    }

    private static Holders Holder(Dictionary<string, Holders> map, string code)
    {
        if (!map.TryGetValue(code, out Holders? h))
        {
            map[code] = h = new Holders();
        }
        return h;
    }

    private static SortedSet<string> Links(Dictionary<string, SortedSet<string>> map, string id)
    {
        if (!map.TryGetValue(id, out SortedSet<string>? set))
        {
            map[id] = set = new SortedSet<string>(StringComparer.Ordinal);
        }
        return set;
    }

    private static IReadOnlyDictionary<string, IReadOnlyList<string>> Freeze(
        Dictionary<string, SortedSet<string>> map) =>
        map.ToDictionary(kv => kv.Key, kv => (IReadOnlyList<string>)[.. kv.Value], StringComparer.Ordinal);
}
