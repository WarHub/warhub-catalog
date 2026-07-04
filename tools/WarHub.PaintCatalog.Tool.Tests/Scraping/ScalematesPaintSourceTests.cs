using WarHub.PaintCatalog.Tool.Scraping;

namespace WarHub.PaintCatalog.Tool.Tests.Scraping;

public class ScalematesPaintSourceTests
{
    // === Card Parsing (listing page) ===

    [Fact]
    public void ParseBrandListingPage_ExtractsPaintsFromRealHtml()
    {
        // Real Scalemates HTML structure with two paint cards
        string html = """
            <h4>Acrylic <span class=ut>(15ml)</span></h4>
            <div class="ac dg bgl cc pr mt4">
              <a href="/colors/two-thin-coats--1055/abyss-blue-abyss-blue-acrylic-matt--39857" class="al p8 c pf">
                <div class="pr dib" style="width:230px;height:138px;background:#344c68">
                  <img src="/colors/img/logos/1055-125068-51-p.jpg" decoding=async class="pnw crl">
                </div>
              </a>
              <div class="ar">
                <a href="/colors/two-thin-coats--1055/abyss-blue-abyss-blue-acrylic-matt--39857" class=pf>
                  <span class="bgb nw">Abyss Blue</span> Abyss Blue
                </a>
                <div class=ut>Two Thin Coats <br>15ml (Bottle)</div>
                <div class="ccf c dib nw bgn">Matt</div>
                <div class="cct c dib nw bgb">Acrylic</div>
              </div>
            </div>
            <div class="ac dg bgl cc pr mt4">
              <a href="/colors/two-thin-coats--1055/ancient-gold-ancient-gold-acrylic-metallic--39950" class="al p8 c pf">
                <div class="pr dib" style="width:230px;height:138px;background:#61553b">
                  <img src="/colors/img/logos/1055-125068-51-p.jpg" loading=lazy class="pnw crl">
                </div>
              </a>
              <div class="ar">
                <a href="/colors/two-thin-coats--1055/ancient-gold-ancient-gold-acrylic-metallic--39950" class=pf>
                  <span class="bgb nw">Ancient Gold</span> Ancient Gold
                </a>
                <div class=ut>Two Thin Coats <br>15ml (Bottle)</div>
                <div class="ccf c dib nw bgn">Metallic</div>
                <div class="cct c dib nw bgb">Acrylic</div>
              </div>
            </div>
            """;

        var paints = ScalematesPaintSource.ParseBrandListingPage(html, "Two Thin Coats");

        Assert.Equal(2, paints.Count);

        var abyssBlue = Assert.Single(paints, p => p.Name == "Abyss Blue");
        Assert.Equal("#344C68", abyssBlue.Hex);
        Assert.Equal(0x34, abyssBlue.R);
        Assert.Equal(0x4C, abyssBlue.G);
        Assert.Equal(0x68, abyssBlue.B);
        Assert.Equal("Matte", abyssBlue.Finish);
        Assert.Equal("Acrylic", abyssBlue.Set);
        Assert.Equal(15, abyssBlue.VolumeMl);
        Assert.Equal("dropper", abyssBlue.Packaging);

        var ancientGold = Assert.Single(paints, p => p.Name == "Ancient Gold");
        Assert.Equal("#61553B", ancientGold.Hex);
        Assert.Equal("Metallic", ancientGold.Finish);
        Assert.Equal("Acrylic", ancientGold.Set);
    }

    [Fact]
    public void ParseBrandListingPage_HandlesEmptyHtml()
    {
        var paints = ScalematesPaintSource.ParseBrandListingPage("<html><body></body></html>", "Brand");

        Assert.Empty(paints);
    }

    [Fact]
    public void ParseBrandListingPage_SkipsCardsWithoutHex()
    {
        string html = """
            <div class="ac dg bgl cc pr mt4">
              <div class="ar">
                <a href="#"><span class="bgb nw">Invisible</span></a>
              </div>
            </div>
            """;

        var paints = ScalematesPaintSource.ParseBrandListingPage(html, "Brand");

        Assert.Empty(paints);
    }

    [Fact]
    public void ParseBrandListingPage_DeduplicatesByName()
    {
        string html = """
            <div class="ac dg bgl cc pr mt4">
              <div style="background:#ff0000"></div>
              <span class="bgb nw">Red</span>
              <div class="ccf c dib nw bgn">Matt</div>
            </div>
            <div class="ac dg bgl cc pr mt4">
              <div style="background:#ff0001"></div>
              <span class="bgb nw">Red</span>
              <div class="ccf c dib nw bgn">Matt</div>
            </div>
            """;

        var paints = ScalematesPaintSource.ParseBrandListingPage(html, "Brand");

        Assert.Single(paints);
    }

    // === Card element extraction ===

    [Fact]
    public void ExtractCardName_ParsesSpanElement()
    {
        string card = """<span class="bgb nw">Abyss Blue</span> Abyss Blue""";

        string? name = ScalematesPaintSource.ExtractCardName(card);

        Assert.Equal("Abyss Blue", name);
    }

    [Fact]
    public void ExtractCardName_ReturnsNull_WhenNoSpan()
    {
        string card = """<div>Just text</div>""";

        string? name = ScalematesPaintSource.ExtractCardName(card);

        Assert.Null(name);
    }

    [Fact]
    public void ExtractCardHex_ParsesBackgroundStyle()
    {
        string card = """<div class="pr dib" style="width:230px;height:138px;background:#344c68">""";

        string? hex = ScalematesPaintSource.ExtractCardHex(card);

        Assert.Equal("#344C68", hex);
    }

    [Fact]
    public void ExtractCardHex_ReturnsNull_WhenNoBackground()
    {
        string card = """<div class="pr dib" style="width:230px">""";

        string? hex = ScalematesPaintSource.ExtractCardHex(card);

        Assert.Null(hex);
    }

    [Theory]
    [InlineData("Matt", "Matte")]
    [InlineData("Metallic", "Metallic")]
    [InlineData("Gloss", "Gloss")]
    [InlineData("Satin", "Satin")]
    public void ExtractCardFinish_ParsesFinishDiv(string rawFinish, string expected)
    {
        string card = $"""<div class="ccf c dib nw bgn">{rawFinish}</div>""";

        string? finish = ScalematesPaintSource.ExtractCardFinish(card);

        Assert.Equal(expected, finish);
    }

    [Fact]
    public void ExtractCardSet_ParsesTypeDiv()
    {
        string card = """<div class="cct c dib nw bgb">Acrylic</div>""";

        string? set = ScalematesPaintSource.ExtractCardSet(card);

        Assert.Equal("Acrylic", set);
    }

    // === Detail page parsing (fallback) ===

    [Fact]
    public void ExtractHexFromSvg_ParsesBackgroundColor()
    {
        string html = """<svg style="background-color:%23344c68" xml:space="preserve">""";

        string? hex = ScalematesPaintSource.ExtractHexFromSvg(html);

        Assert.Equal("#344C68", hex);
    }

    [Fact]
    public void ExtractHexFromSvg_ParsesHashFormat()
    {
        string html = """<svg style="background-color:#ff0000" xml:space="preserve">""";

        string? hex = ScalematesPaintSource.ExtractHexFromSvg(html);

        Assert.Equal("#FF0000", hex);
    }

    [Fact]
    public void ExtractHexFromSvg_ReturnsNull_WhenNoMatch()
    {
        string html = """<svg style="background-color:rgb(255,0,0)">""";

        string? hex = ScalematesPaintSource.ExtractHexFromSvg(html);

        Assert.Null(hex);
    }

    [Fact]
    public void ExtractHexFromColorViewer_ParsesRgbLink()
    {
        string html = """<a href="/colors/rgb.php?id=344c68">#344c68</a>""";

        string? hex = ScalematesPaintSource.ExtractHexFromColorViewer(html);

        Assert.Equal("#344C68", hex);
    }

    // === Finish from slug ===

    [Fact]
    public void ExtractFinishFromSlug_DetectsMatt()
    {
        string? finish = ScalematesPaintSource.ExtractFinishFromSlug("abyss-blue-abyss-blue-acrylic-matt--39857");

        Assert.Equal("Matte", finish);
    }

    [Fact]
    public void ExtractFinishFromSlug_DetectsMetallic()
    {
        string? finish = ScalematesPaintSource.ExtractFinishFromSlug("ancient-gold-ancient-gold-acrylic-metallic--39950");

        Assert.Equal("Metallic", finish);
    }

    [Fact]
    public void ExtractFinishFromSlug_DetectsGloss()
    {
        string? finish = ScalematesPaintSource.ExtractFinishFromSlug("some-paint-enamel-gloss--12345");

        Assert.Equal("Gloss", finish);
    }

    [Fact]
    public void ExtractFinishFromSlug_ReturnsNull_WhenNoFinish()
    {
        string? finish = ScalematesPaintSource.ExtractFinishFromSlug("some-paint--12345");

        Assert.Null(finish);
    }

    // === Name derivation from slug ===

    [Theory]
    [InlineData("abyss-blue-abyss-blue-acrylic-matt--39857", "Abyss Blue")]
    [InlineData("ancient-gold-ancient-gold-acrylic-metallic--39950", "Ancient Gold")]
    [InlineData("bone-wash-bone-wash-acrylic-matt--39942", "Bone Wash")]
    public void DerivePaintNameFromSlug_ExtractsName(string slug, string expectedName)
    {
        string? name = ScalematesPaintSource.DerivePaintNameFromSlug(slug);

        Assert.Equal(expectedName, name);
    }

    [Fact]
    public void DeduplicateName_RemovesDuplicates()
    {
        string result = ScalematesPaintSource.DeduplicateName("Abyss Blue Abyss Blue");

        Assert.Equal("Abyss Blue", result);
    }

    [Fact]
    public void DeduplicateName_LeavesNonDuplicates()
    {
        string result = ScalematesPaintSource.DeduplicateName("Abyss Blue");

        Assert.Equal("Abyss Blue", result);
    }

    // === Volume and packaging ===

    [Fact]
    public void ExtractVolumeFromPage_ParsesMilliliters()
    {
        string html = """<div>15ml (Bottle)</div>""";

        int? volume = ScalematesPaintSource.ExtractVolumeFromPage(html);

        Assert.Equal(15, volume);
    }

    [Fact]
    public void ExtractPackagingFromPage_ParsesBottle()
    {
        string html = """<div>(15ml Bottle)</div>""";

        string? packaging = ScalematesPaintSource.ExtractPackagingFromPage(html);

        Assert.Equal("dropper", packaging);
    }

    [Fact]
    public void ExtractPackagingFromPage_ParsesPot()
    {
        string html = """<div>(12ml Pot)</div>""";

        string? packaging = ScalematesPaintSource.ExtractPackagingFromPage(html);

        Assert.Equal("pot", packaging);
    }

    // === Detail page (fallback) ===

    [Fact]
    public void ParsePaintDetailPage_ParsesCompletePaint()
    {
        string html = """
            <svg style="background-color:%23344c68">content</svg>
            <a href="/colors/rgb.php?id=344c68">#344c68</a>
            Finish:</td>
            Matt
            <td>
            15ml (Bottle)
            """;

        var paint = ScalematesPaintSource.ParsePaintDetailPage(html, "Abyss Blue", "Two Thin Coats", "Matte");

        Assert.NotNull(paint);
        Assert.Equal("Abyss Blue", paint.Name);
        Assert.Equal("#344C68", paint.Hex);
        Assert.Equal(0x34, paint.R);
        Assert.Equal(0x4C, paint.G);
        Assert.Equal(0x68, paint.B);
        Assert.Equal(15, paint.VolumeMl);
    }

    [Fact]
    public void ParsePaintDetailPage_ReturnsNull_WhenNoHex()
    {
        string html = "<div>No color data here</div>";

        var paint = ScalematesPaintSource.ParsePaintDetailPage(html, "Test", "Brand", null);

        Assert.Null(paint);
    }

    // === Hex parsing ===

    [Theory]
    [InlineData("#344C68", true, 0x34, 0x4C, 0x68)]
    [InlineData("#FF0000", true, 0xFF, 0x00, 0x00)]
    [InlineData("#invalid", false, 0, 0, 0)]
    [InlineData("#12", false, 0, 0, 0)]
    public void TryParseHex_ParsesCorrectly(string hex, bool expected, int er, int eg, int eb)
    {
        bool result = ScalematesPaintSource.TryParseHex(hex, out int r, out int g, out int b);

        Assert.Equal(expected, result);
        if (expected)
        {
            Assert.Equal(er, r);
            Assert.Equal(eg, g);
            Assert.Equal(eb, b);
        }
    }
}
