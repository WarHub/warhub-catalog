using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization.Metadata;
using Microsoft.Data.Sqlite;

namespace WarHub.Catalog.Publish;

/// <summary>
/// Writes <c>dist/catalog.sqlite</c>: the published products, paints and barcode links as SQL
/// tables, for a consumer (or a session) that wants to ask a question of the whole catalog without
/// loading 20 MB of JSON and joining it by hand.
///
/// DERIVED OUTPUT ONLY. It is built from the same in-memory records the JSON documents were
/// serialized from, after the link pass, and nothing in this repository reads it back -- the YAML
/// under data/ stays the one source of truth, and the JSON stays the contract.
///
/// THE COLUMNS ARE THE JSON CONTRACT, not a second list of it. Each table takes its columns from
/// the record type's own JSON metadata (<see cref="JsonConfig.Options"/>): the same names, in the
/// same order, so a field added to <see cref="ProductRecord"/> or <see cref="PaintRecord"/> is a
/// column here on the next publish with nothing to keep in step. A scalar is stored as itself; an
/// array or object is stored as the JSON text the documents carry, which SQLite's json_each()
/// reads. An absent property is NULL, as the JSON omits it.
///
/// Rows go in by id and the whole file is written in one transaction to a fresh path, so the same
/// input produces the same bytes and the manifest's sha256 is reproducible.
/// </summary>
internal static class QueryDatabase
{
    public const string ProductsTable = "products";
    public const string PaintsTable = "paints";
    public const string BarcodesTable = "barcodes";

    public static void Write(
        string path,
        IEnumerable<ProductRecord> products,
        IEnumerable<PaintRecord> paints,
        BarcodeIndex barcodes,
        Provenance prov)
    {
        // Pooling off, so disposing the connection releases the file: the publisher hashes it next,
        // and Windows will not let a test fixture delete a file a pooled handle still holds.
        string connectionString = new SqliteConnectionStringBuilder
        {
            DataSource = path,
            Mode = SqliteOpenMode.ReadWriteCreate,
            Pooling = false,
        }.ToString();

        using var connection = new SqliteConnection(connectionString);
        connection.Open();
        using SqliteTransaction transaction = connection.BeginTransaction();

        Execute(connection, transaction, """
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)
            """);
        var meta = new List<(string, string?)>
        {
            ("schemaVersion", SchemaInfo.SchemaVersion),
            ("version", prov.Version),
            ("generatedAt", prov.GeneratedAt),
            ("gitCommit", prov.GitCommit),
        };
        using (SqliteCommand insert = Prepare(connection, transaction, "meta", ["key", "value"]))
        {
            foreach ((string key, string? value) in meta.Where(m => m.Item2 is not null))
            {
                Insert(insert, [key, value]);
            }
        }

        WriteRecords(connection, transaction, ProductsTable,
            products.OrderBy(p => p.Id, StringComparer.Ordinal));
        WriteRecords(connection, transaction, PaintsTable,
            paints.OrderBy(p => p.Id, StringComparer.Ordinal));

        // barcodes.json keyed by barcode, one row per record carrying it: the index is a map to a
        // LIST, and a barcode two records share is exactly the case a consumer queries it for.
        Execute(connection, transaction, $"""
            CREATE TABLE {BarcodesTable} (
              barcode TEXT NOT NULL,
              catalog TEXT NOT NULL,
              id TEXT NOT NULL,
              PRIMARY KEY (barcode, catalog, id)
            )
            """);
        using (SqliteCommand insert = Prepare(connection, transaction, BarcodesTable, ["barcode", "catalog", "id"]))
        {
            foreach ((string barcode, IReadOnlyList<BarcodeRef> refs) in barcodes.Barcodes
                .OrderBy(b => b.Key, StringComparer.Ordinal))
            {
                foreach (BarcodeRef r in refs)
                {
                    Insert(insert, [barcode, r.Catalog, r.Id]);
                }
            }
        }

        transaction.Commit();
    }

    private static void WriteRecords<T>(
        SqliteConnection connection, SqliteTransaction transaction, string table, IEnumerable<T> records)
    {
        IReadOnlyList<JsonPropertyInfo> columns = Columns<T>();
        string definitions = string.Join(",\n  ", columns.Select(c =>
            $"\"{c.Name}\" {SqlType(c.PropertyType)}{(c.Name == "id" ? " PRIMARY KEY" : "")}"));
        Execute(connection, transaction, $"CREATE TABLE {table} (\n  {definitions}\n)");

        using SqliteCommand insert = Prepare(connection, transaction, table, [.. columns.Select(c => c.Name)]);
        foreach (T record in records)
        {
            Insert(insert, [.. columns.Select(c => Value(c.Get!(record!)))]);
        }
    }

    /// <summary>The record's JSON properties, in the order the documents serialize them.</summary>
    private static IReadOnlyList<JsonPropertyInfo> Columns<T>()
    {
        JsonTypeInfo info = JsonConfig.Options.GetTypeInfo(typeof(T));
        return [.. info.Properties.Where(p => p.Get is not null).OrderBy(p => p.Order)];
    }

    private static string SqlType(Type type)
    {
        Type t = Nullable.GetUnderlyingType(type) ?? type;
        if (t == typeof(string)) return "TEXT";
        if (t == typeof(int) || t == typeof(long) || t == typeof(bool)) return "INTEGER";
        if (t == typeof(decimal) || t == typeof(double) || t == typeof(float)) return "REAL";
        return "TEXT"; // an array or object, stored as its JSON
    }

    private static object? Value(object? value) => value switch
    {
        null => null,
        string s => s,
        int or long => value,
        bool b => b ? 1 : 0,
        decimal d => (double)d,
        double or float => Convert.ToDouble(value, CultureInfo.InvariantCulture),
        _ => JsonSerializer.Serialize(value, value.GetType(), JsonConfig.Options),
    };

    private static SqliteCommand Prepare(
        SqliteConnection connection, SqliteTransaction transaction, string table, IReadOnlyList<string> columns)
    {
        SqliteCommand command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText =
            $"INSERT INTO {table} ({string.Join(", ", columns.Select(c => $"\"{c}\""))}) "
            + $"VALUES ({string.Join(", ", columns.Select((_, i) => $"$p{i}"))})";
        for (int i = 0; i < columns.Count; i++)
        {
            command.Parameters.Add(new SqliteParameter($"$p{i}", null));
        }
        return command;
    }

    private static void Insert(SqliteCommand command, IReadOnlyList<object?> values)
    {
        for (int i = 0; i < values.Count; i++)
        {
            command.Parameters[i].Value = values[i] ?? DBNull.Value;
        }
        command.ExecuteNonQuery();
    }

    private static void Execute(SqliteConnection connection, SqliteTransaction transaction, string sql)
    {
        using SqliteCommand command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = sql;
        command.ExecuteNonQuery();
    }
}
