using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace WarHub.CatalogStore;

/// <summary>
/// Shared YAML (de)serializer for all catalog data files. Deterministic and
/// stable: force-quotes ambiguous scalars, omits nulls, disables anchors/aliases.
/// </summary>
public static class CatalogSerializer
{
    public static ISerializer CreateSerializer() =>
        new SerializerBuilder()
            .WithNamingConvention(CamelCaseNamingConvention.Instance)
            .WithEventEmitter(next => new QuotingEventEmitter(next))
            .ConfigureDefaultValuesHandling(DefaultValuesHandling.OmitNull)
            .DisableAliases()
            .Build();

    public static IDeserializer CreateDeserializer() =>
        new DeserializerBuilder()
            .WithNamingConvention(CamelCaseNamingConvention.Instance)
            .IgnoreUnmatchedProperties()
            .Build();
}
