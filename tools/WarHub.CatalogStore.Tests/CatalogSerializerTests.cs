namespace WarHub.CatalogStore.Tests;

public class CatalogSerializerTests
{
    private sealed record Sample
    {
        public required string Ean { get; init; }
        public string? Note { get; init; }
        public required string Plain { get; init; }
    }

    [Fact]
    public void Serialize_AllDigitString_IsQuoted_AndRoundTripsAsString()
    {
        var serializer = CatalogSerializer.CreateSerializer();
        var deserializer = CatalogSerializer.CreateDeserializer();

        var obj = new Sample { Ean = "0889696010223", Plain = "Space Marines" };
        string yaml = serializer.Serialize(obj);

        Assert.Contains("ean: '0889696010223'", yaml);
        // Plain text stays unquoted for readability.
        Assert.Contains("plain: Space Marines", yaml);

        Sample back = deserializer.Deserialize<Sample>(yaml);
        Assert.Equal("0889696010223", back.Ean);
    }

    [Fact]
    public void Serialize_MultiLineString_UsesBlockScalar()
    {
        var serializer = CatalogSerializer.CreateSerializer();
        var obj = new Sample { Ean = "1", Plain = "x", Note = "line one\nline two" };
        string yaml = serializer.Serialize(obj);
        Assert.Contains("note: |", yaml);
    }

    [Theory]
    [InlineData("true")]
    [InlineData("null")]
    [InlineData("2026-07-07")]
    [InlineData("12.5")]
    [InlineData(".5")]
    [InlineData("1e10")]
    [InlineData(".inf")]
    [InlineData(".nan")]
    [InlineData("0x1A")]
    [InlineData("0o17")]
    [InlineData("+42")]
    [InlineData("2026-07-07 12:00:00")]
    public void Serialize_AmbiguousScalars_AreQuoted(string value)
    {
        var serializer = CatalogSerializer.CreateSerializer();
        var obj = new Sample { Ean = value, Plain = "x" };
        string yaml = serializer.Serialize(obj);
        Assert.Contains($"ean: '{value}'", yaml);
    }

    [Fact]
    public void Serialize_OmitsNulls()
    {
        var serializer = CatalogSerializer.CreateSerializer();
        var obj = new Sample { Ean = "1", Plain = "x", Note = null };
        string yaml = serializer.Serialize(obj);
        Assert.DoesNotContain("note:", yaml);
    }

    [Theory]
    [InlineData("Space Marines")]
    [InlineData("Episode 4")]
    [InlineData("Product 123")]
    [InlineData("Wardens of the North")]
    public void Serialize_PlainProse_IsNotQuoted(string value)
    {
        var serializer = CatalogSerializer.CreateSerializer();
        var obj = new Sample { Ean = "1", Plain = value };
        string yaml = serializer.Serialize(obj);
        Assert.Contains($"plain: {value}", yaml);
    }

    [Fact]
    public void Quotes_RealDate()
    {
        var serializer = CatalogSerializer.CreateSerializer();
        var obj = new Sample { Ean = "2026-07-08", Plain = "x" };
        string yaml = serializer.Serialize(obj);
        Assert.Contains("ean: '2026-07-08'", yaml);
    }

    [Fact]
    public void Quotes_Timestamp()
    {
        var serializer = CatalogSerializer.CreateSerializer();
        var obj = new Sample { Ean = "2026-07-08T12:00:00Z", Plain = "x" };
        string yaml = serializer.Serialize(obj);
        Assert.Contains("ean: '2026-07-08T12:00:00Z'", yaml);
    }

    [Fact]
    public void DoesNotQuote_DatePrefixedTitle()
    {
        var serializer = CatalogSerializer.CreateSerializer();
        var obj = new Sample { Ean = "1", Plain = "2024-01-01 Anniversary Edition" };
        string yaml = serializer.Serialize(obj);
        Assert.Contains("plain: 2024-01-01 Anniversary Edition", yaml);
        Assert.DoesNotContain("plain: '2024-01-01 Anniversary Edition'", yaml);
    }

    [Fact]
    public void Quotes_SignedHex()
    {
        var serializer = CatalogSerializer.CreateSerializer();
        var obj = new Sample { Ean = "-0x1A", Plain = "x" };
        string yaml = serializer.Serialize(obj);
        Assert.Contains("ean: '-0x1A'", yaml);
    }
}
