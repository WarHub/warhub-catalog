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
}
