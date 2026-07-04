using System.Net;
using System.Text.RegularExpressions;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Scraping;

/// <summary>
/// Scrapes paint data from Scalemates.com color database.
/// Scalemates has structured paint data with hex codes, finish, and type
/// for brands not covered by Arcturus5404 (e.g., Two Thin Coats).
///
/// The listing page contains all paint data in card blocks, so only one
/// HTTP request per page is needed (no individual paint page fetching).
/// </summary>
public sealed partial class ScalematesPaintSource : IDisposable
{
    private readonly HttpClient _httpClient;
    private readonly TimeSpan _requestDelay;
    private readonly bool _verbose;
    private DateTime _lastRequest = DateTime.MinValue;

    private const string BaseUrl = "https://www.scalemates.com";

    public ScalematesPaintSource(TimeSpan? requestDelay = null, bool verbose = false)
    {
        _requestDelay = requestDelay ?? TimeSpan.FromMilliseconds(1500);
        _verbose = verbose;

        _httpClient = new HttpClient(new HttpClientHandler
        {
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
        });
        _httpClient.DefaultRequestHeaders.UserAgent.ParseAdd(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36");
        _httpClient.DefaultRequestHeaders.Accept.ParseAdd("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8");
        _httpClient.DefaultRequestHeaders.AcceptLanguage.ParseAdd("en-US,en;q=0.9");
    }

    /// <summary>
    /// Fetches all paints for a brand from Scalemates.
    /// The listing page contains complete data (hex, name, finish, volume),
    /// so only one request per page is needed.
    /// </summary>
    /// <param name="brandPath">The Scalemates brand path, e.g., "two-thin-coats--1055"</param>
    /// <param name="brandDisplayName">Display name for the brand</param>
    /// <param name="ct">Cancellation token</param>
    public async Task<IReadOnlyList<Paint>> FetchBrandPaintsAsync(
        string brandPath,
        string brandDisplayName,
        CancellationToken ct = default)
    {
        var paints = new List<Paint>();

        string? listingUrl = $"{BaseUrl}/colors/{brandPath}/";
        if (_verbose) Console.WriteLine($"  Fetching brand listing: {listingUrl}");

        while (listingUrl is not null)
        {
            await RateLimitAsync(ct);

            string html;
            try
            {
                html = await _httpClient.GetStringAsync(listingUrl, ct);
            }
            catch (HttpRequestException ex)
            {
                if (_verbose) Console.WriteLine($"    Error fetching listing: {ex.Message}");
                break;
            }

            var pageResults = ParseBrandListingPage(html, brandDisplayName);
            paints.AddRange(pageResults);

            if (_verbose) Console.WriteLine($"    Found {pageResults.Count} paints on page (total: {paints.Count})");

            listingUrl = ExtractNextPageUrl(html);
        }

        if (_verbose) Console.WriteLine($"    Scraped {paints.Count} paints with color data");

        return paints;
    }

    /// <summary>
    /// Parses a brand listing page to extract complete paint data from card blocks.
    ///
    /// Each paint card in real Scalemates HTML has this structure:
    /// <code>
    /// &lt;div class="ac ..."&gt;
    ///   &lt;a href="/colors/brand/slug"&gt;
    ///     &lt;div style="...background:#RRGGBB"&gt;...&lt;/div&gt;
    ///   &lt;/a&gt;
    ///   &lt;div class="ar"&gt;
    ///     &lt;a href="..."&gt;&lt;span class="bgb nw"&gt;Name&lt;/span&gt; Name&lt;/a&gt;
    ///     &lt;div class=ut&gt;Brand &lt;br&gt;15ml (Bottle)&lt;/div&gt;
    ///     &lt;div class="ccf ..."&gt;Matt&lt;/div&gt;
    ///     &lt;div class="cct ..."&gt;Acrylic&lt;/div&gt;
    ///   &lt;/div&gt;
    /// &lt;/div&gt;
    /// </code>
    /// </summary>
    internal static List<Paint> ParseBrandListingPage(string html, string brandDisplayName)
    {
        var paints = new List<Paint>();

        // Split into card blocks - each starts with <div class="ac
        string[] cardBlocks = CardSplitPattern().Split(html);

        foreach (string card in cardBlocks)
        {
            if (card.Length < 50)
                continue;

            // Extract paint name from <span class="bgb nw">Name</span>
            string? name = ExtractCardName(card);
            if (string.IsNullOrEmpty(name))
                continue;

            // Extract hex from background:#RRGGBB in the card's style
            string? hex = ExtractCardHex(card);
            if (hex is null)
                continue;

            if (!TryParseHex(hex, out int r, out int g, out int b))
                continue;

            // Extract finish from <div class="ccf...">Matt/Metallic</div>
            string? finish = ExtractCardFinish(card);

            // Extract set/type from <div class="cct...">Acrylic</div>
            string set = ExtractCardSet(card) ?? "Acrylic";

            // Extract volume and packaging from "15ml (Bottle)"
            int? volumeMl = ExtractVolumeFromPage(card);
            string? packaging = ExtractPackagingFromPage(card);

            // Deduplicate by name (cards appear once per paint, but be safe)
            if (paints.Any(p => string.Equals(p.Name, name, StringComparison.OrdinalIgnoreCase)))
                continue;

            paints.Add(new Paint
            {
                Name = name,
                Set = set,
                R = r,
                G = g,
                B = b,
                Hex = hex,
                VolumeMl = volumeMl,
                Packaging = packaging,
                Finish = finish,
                IsDiscontinued = false,
            });
        }

        return paints;
    }

    /// <summary>
    /// Extracts paint name from a card's <![CDATA[<span class="bgb nw">Name</span>]]> element.
    /// </summary>
    internal static string? ExtractCardName(string card)
    {
        Match match = CardNamePattern().Match(card);
        if (match.Success)
        {
            string rawName = WebUtility.HtmlDecode(match.Groups["name"].Value.Trim());
            return string.IsNullOrWhiteSpace(rawName) ? null : rawName;
        }
        return null;
    }

    /// <summary>
    /// Extracts hex color from a card's background:#RRGGBB style.
    /// </summary>
    internal static string? ExtractCardHex(string card)
    {
        Match match = CardBackgroundHexPattern().Match(card);
        if (match.Success)
        {
            string hexValue = match.Groups["hex"].Value;
            return $"#{hexValue.ToUpperInvariant()}";
        }
        return null;
    }

    /// <summary>
    /// Extracts finish from a card's <![CDATA[<div class="ccf...">Matt</div>]]> element.
    /// </summary>
    internal static string? ExtractCardFinish(string card)
    {
        Match match = CardFinishPattern().Match(card);
        if (match.Success)
        {
            string finish = match.Groups["finish"].Value.Trim();
            return NormalizeFinish(finish);
        }
        return null;
    }

    /// <summary>
    /// Extracts set/type from a card's <![CDATA[<div class="cct...">Acrylic</div>]]> element.
    /// </summary>
    internal static string? ExtractCardSet(string card)
    {
        Match match = CardSetPattern().Match(card);
        return match.Success ? WebUtility.HtmlDecode(match.Groups["set"].Value.Trim()) : null;
    }

    /// <summary>
    /// Parses an individual paint detail page for hex code and metadata.
    /// Kept as fallback for cases where listing page doesn't have all data.
    /// </summary>
    internal static Paint? ParsePaintDetailPage(string html, string name, string brandDisplayName, string? listFinish)
    {
        string? hex = ExtractHexFromSvg(html);
        hex ??= ExtractHexFromColorViewer(html);

        if (hex is null)
            return null;

        if (!TryParseHex(hex, out int r, out int g, out int b))
            return null;

        string? detailFinish = ExtractFinishFromDetailPage(html);
        string? finish = detailFinish ?? listFinish;

        int? volumeMl = ExtractVolumeFromPage(html);
        string? packaging = ExtractPackagingFromPage(html);
        string set = ExtractSetFromPage(html) ?? "Acrylic";

        return new Paint
        {
            Name = name,
            Set = set,
            R = r,
            G = g,
            B = b,
            Hex = hex,
            VolumeMl = volumeMl,
            Packaging = packaging,
            Finish = finish,
            IsDiscontinued = false
        };
    }

    internal static string? ExtractHexFromSvg(string html)
    {
        Match match = SvgBackgroundColorPattern().Match(html);
        if (match.Success)
        {
            string hexValue = match.Groups["hex"].Value;
            return $"#{hexValue.ToUpperInvariant()}";
        }
        return null;
    }

    internal static string? ExtractHexFromColorViewer(string html)
    {
        Match match = RgbLinkPattern().Match(html);
        if (match.Success)
        {
            string hexValue = match.Groups["hex"].Value;
            return $"#{hexValue.ToUpperInvariant()}";
        }
        return null;
    }

    internal static string? ExtractFinishFromDetailPage(string html)
    {
        Match match = FinishPattern().Match(html);
        if (match.Success)
        {
            string finish = match.Groups["finish"].Value.Trim();
            return NormalizeFinish(finish);
        }
        return null;
    }

    internal static string? ExtractFinishFromSlug(string slug)
    {
        if (slug.Contains("-metallic-", StringComparison.OrdinalIgnoreCase) ||
            slug.EndsWith("-metallic", StringComparison.OrdinalIgnoreCase))
            return "Metallic";
        if (slug.Contains("-gloss-", StringComparison.OrdinalIgnoreCase) ||
            slug.EndsWith("-gloss", StringComparison.OrdinalIgnoreCase))
            return "Gloss";
        if (slug.Contains("-satin-", StringComparison.OrdinalIgnoreCase) ||
            slug.EndsWith("-satin", StringComparison.OrdinalIgnoreCase))
            return "Satin";
        if (slug.Contains("-matt-", StringComparison.OrdinalIgnoreCase) ||
            slug.EndsWith("-matt", StringComparison.OrdinalIgnoreCase))
            return "Matte";
        return null;
    }

    internal static int? ExtractVolumeFromPage(string html)
    {
        Match match = VolumePattern().Match(html);
        if (match.Success && int.TryParse(match.Groups["vol"].Value, out int vol))
            return vol;
        return null;
    }

    internal static string? ExtractPackagingFromPage(string html)
    {
        Match match = PackagingPattern().Match(html);
        if (match.Success)
        {
            string pkg = match.Groups["pkg"].Value.Trim().ToLowerInvariant();
            return pkg switch
            {
                "bottle" => "dropper",
                "pot" => "pot",
                "jar" => "jar",
                "tin" => "tin",
                "spray" or "spray can" => "spray",
                _ => pkg
            };
        }
        return null;
    }

    internal static string? ExtractSetFromPage(string html)
    {
        Match match = SetPattern().Match(html);
        return match.Success ? WebUtility.HtmlDecode(match.Groups["set"].Value.Trim()) : null;
    }

    internal static string DeduplicateName(string name)
    {
        int half = name.Length / 2;
        if (half > 0)
        {
            string first = name[..half].TrimEnd();
            string second = name[half..].TrimStart();
            if (string.Equals(first, second, StringComparison.OrdinalIgnoreCase))
                return first;
        }

        return name;
    }

    internal static string? DerivePaintNameFromSlug(string slug)
    {
        int idSep = slug.LastIndexOf("--", StringComparison.Ordinal);
        if (idSep >= 0)
            slug = slug[..idSep];

        slug = StripTypeSuffixPattern().Replace(slug, "");

        string[] words = slug.Split('-', StringSplitOptions.RemoveEmptyEntries);
        if (words.Length >= 2 && words.Length % 2 == 0)
        {
            int half = words.Length / 2;
            string[] firstHalf = words[..half];
            string[] secondHalf = words[half..];
            bool isDuplicate = firstHalf.Zip(secondHalf)
                .All(pair => string.Equals(pair.First, pair.Second, StringComparison.OrdinalIgnoreCase));
            if (isDuplicate)
                words = firstHalf;
        }

        if (words.Length == 0)
            return null;

        return string.Join(' ', words.Select(w =>
            char.ToUpperInvariant(w[0]) + w[1..]));
    }

    private static string? NormalizeFinish(string finish)
    {
        return finish.ToLowerInvariant() switch
        {
            "matt" or "matte" or "flat" => "Matte",
            "metallic" => "Metallic",
            "gloss" or "glossy" => "Gloss",
            "satin" or "semi-gloss" or "semi gloss" => "Satin",
            _ => finish
        };
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

    private static string? ExtractNextPageUrl(string html)
    {
        Match match = NextPagePattern().Match(html);
        if (match.Success)
        {
            string path = match.Groups["path"].Value;
            return $"{BaseUrl}{path}";
        }
        return null;
    }

    private async Task RateLimitAsync(CancellationToken ct)
    {
        TimeSpan elapsed = DateTime.UtcNow - _lastRequest;
        if (elapsed < _requestDelay)
        {
            await Task.Delay(_requestDelay - elapsed, ct);
        }
        _lastRequest = DateTime.UtcNow;
    }

    public void Dispose()
    {
        _httpClient.Dispose();
    }

    // Regex patterns for listing page card parsing

    // Splits HTML into card blocks; each card starts with <div class="ac
    [GeneratedRegex(@"<div\s+class=""ac\s", RegexOptions.Compiled)]
    private static partial Regex CardSplitPattern();

    // Extracts paint name from <span class="bgb nw">Name</span>
    [GeneratedRegex(@"<span\s+class=""bgb\s+nw"">(?<name>[^<]+)</span>", RegexOptions.Compiled)]
    private static partial Regex CardNamePattern();

    // Extracts hex from background:#RRGGBB in inline style
    [GeneratedRegex(@"background:#(?<hex>[0-9a-fA-F]{6})", RegexOptions.Compiled)]
    private static partial Regex CardBackgroundHexPattern();

    // Extracts finish from <div class="ccf ...">Matt</div>
    [GeneratedRegex(@"<div\s+class=""ccf[^""]*"">(?<finish>[^<]+)</div>", RegexOptions.Compiled)]
    private static partial Regex CardFinishPattern();

    // Extracts set/type from <div class="cct ...">Acrylic</div>
    [GeneratedRegex(@"<div\s+class=""cct[^""]*"">(?<set>[^<]+)</div>", RegexOptions.Compiled)]
    private static partial Regex CardSetPattern();

    // Regex patterns for detail page parsing (fallback)

    [GeneratedRegex(@"background-color:[%23#]+(?<hex>[0-9a-fA-F]{6})", RegexOptions.Compiled)]
    private static partial Regex SvgBackgroundColorPattern();

    [GeneratedRegex(@"/colors/rgb\.php\?id=(?<hex>[0-9a-fA-F]{6})", RegexOptions.Compiled)]
    private static partial Regex RgbLinkPattern();

    [GeneratedRegex(@"Finish:\s*</\w+>\s*(?<finish>[A-Za-z /-]+?)(?:\s*<|\s*\n)", RegexOptions.Compiled)]
    private static partial Regex FinishPattern();

    [GeneratedRegex(@"(?<vol>\d+)\s*ml\b", RegexOptions.IgnoreCase | RegexOptions.Compiled)]
    private static partial Regex VolumePattern();

    [GeneratedRegex(@"\((?:(?<vol>\d+)ml\s+)?(?<pkg>Bottle|Pot|Jar|Tin|Spray|Spray Can)\)", RegexOptions.IgnoreCase | RegexOptions.Compiled)]
    private static partial Regex PackagingPattern();

    [GeneratedRegex(@"Range:\s*</\w+>\s*<[^>]*>(?<set>[^<]+)</", RegexOptions.Compiled)]
    private static partial Regex SetPattern();

    [GeneratedRegex(@"-(?:acrylic|enamel|lacquer|oil)-(?:matt|metallic|gloss|satin|flat|semi-gloss)$", RegexOptions.IgnoreCase | RegexOptions.Compiled)]
    private static partial Regex StripTypeSuffixPattern();

    [GeneratedRegex(@"""next""[^>]*href=""(?<path>[^""]+)""", RegexOptions.Compiled)]
    private static partial Regex NextPagePattern();
}
