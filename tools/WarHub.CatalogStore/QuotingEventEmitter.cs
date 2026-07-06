using System.Text.RegularExpressions;
using YamlDotNet.Core;
using YamlDotNet.Core.Events;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.EventEmitters;

namespace WarHub.CatalogStore;

/// <summary>
/// Forces string scalars that would otherwise round-trip as a non-string
/// (integers, floats, booleans, nulls, dates) to be emitted single-quoted,
/// and multi-line strings to use literal block style. This prevents
/// schema-less parsers from re-typing values like EAN "0889…" as numbers.
/// </summary>
public sealed partial class QuotingEventEmitter(IEventEmitter next) : ChainedEventEmitter(next)
{
    // Core-schema-ambiguous plain scalars: integers (incl. leading zeros, hex, octal),
    // floats (incl. leading-dot, exponent, .inf/.nan), booleans, nulls, and dates/timestamps.
    [GeneratedRegex(
        @"^([-+]?\d+|0x[0-9a-fA-F]+|0o[0-7]+|[-+]?(\d+\.\d*|\.\d+)([eE][-+]?\d+)?|[-+]?\d+[eE][-+]?\d+|[-+]?\.(inf|nan)|true|false|yes|no|on|off|null|~|\d{4}-\d{2}-\d{2}([Tt ].*)?)$",
        RegexOptions.IgnoreCase)]
    private static partial Regex Ambiguous();

    public override void Emit(ScalarEventInfo eventInfo, IEmitter emitter)
    {
        if (eventInfo.Source.Type == typeof(string) &&
            eventInfo.Source.Value is string text)
        {
            if (text.Contains('\n'))
                eventInfo.Style = ScalarStyle.Literal;
            else if (text.Length > 0 && Ambiguous().IsMatch(text))
                eventInfo.Style = ScalarStyle.SingleQuoted;
        }

        base.Emit(eventInfo, emitter);
    }
}
