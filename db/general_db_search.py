import db.db_helpers as helpers
import json
import builtins
import config
from typing import TypedDict, Literal, Union, Optional
import pandas as pd
from datetime import datetime

def convert_to_unix(date_input):
    if pd.isna(date_input):
        return None
    if isinstance(date_input, (int, float)) and date_input > 1e9:
        return date_input
    return int(pd.to_datetime(date_input).timestamp())

def convert_from_unix(unix_timestamp, output_format='datetime'):
    if pd.isna(unix_timestamp):
        return None
    dt = datetime.fromtimestamp(unix_timestamp)
    if output_format == 'datetime':
        return dt
    elif output_format == 'date':
        return dt.date()
    elif output_format == 'str':
        return dt.strftime('%Y-%m-%d')

# Aggregation Functions:
AggregationFunction = Literal["SUM", "AVG", "COUNT", "MIN", "MAX"]

class AggregationDefinition(TypedDict):
    field: str
    function: AggregationFunction

Aggregation = dict[str, AggregationDefinition]

# Filter:
class FilterCondition(TypedDict):
    field: str
    op: str
    value: Union[str, int, float, list, tuple]

Filters = list[FilterCondition]

# Group By:
GroupBy = list[str]

# Having:
class HavingCondition(TypedDict):
    aggregation: str  # Von 'field' zu 'aggregation' ändern
    op: Literal["=", "!=", "<", "<=", ">", ">="]
    value: Union[int, float]

Having = list[HavingCondition]

def is_aggregation_field(field: str) -> bool:
    """Check if field is an aggregation expression like 'AVG(games.rating)'"""
    aggregation_functions = ["SUM", "AVG", "COUNT", "MIN", "MAX"]
    return any(field.upper().startswith(f"{func}(") for func in aggregation_functions)

def validate_get_data_input(
    fields: list[str],
    sort_fields: Optional[list[dict[str, str]]],
    filters: Filters,
    aggregation: Optional[Aggregation] = None,
    group_by: Optional[GroupBy] = None,
    limit: Optional[int] = None,
    having: Optional[Having] = None,
    offset: Optional[int] = None
) -> None:
    if not fields:
        raise ValueError("Field is missing")

    if fields == ["*"]:
        raise ValueError("Wildcard not allowed")

    with open(config.QUERY_WHITELIST_PATH, "r", encoding="utf-8") as f:
        whitelist = json.load(f)
        allowed_fields = set(whitelist)

        for field in fields:
            # Skip validation for aggregation fields like "AVG(games.rating)"
            if is_aggregation_field(field):
                continue

            # Skip if field is an aggregation alias
            if aggregation and field in aggregation:
                continue

            if field not in allowed_fields:
                raise ValueError(f"Field '{field}' not allowed")

            
        if sort_fields:
            for sort_field in sort_fields:
                field = sort_field["field"]
                # Skip validation for aggregation fields in sort
                if is_aggregation_field(field):
                    continue
                    
                if field not in allowed_fields:
                    raise ValueError(f"Sort-field '{field}' not allowed")
                if sort_field["direction"] not in ["ASC", "DESC"]:
                    raise ValueError(f"Sort-direction {sort_field['direction']} not allowed")

        if filters:
            for f in filters:
                field = f["field"]
                op = f["op"]
                value = f["value"]

                # Skip validation for aggregation fields in filters
                if is_aggregation_field(field):
                    continue
                    
                if field not in allowed_fields:
                    raise ValueError(f"Filter field '{field}' not allowed")

                allowed_ops = whitelist[field]["operators"]
                type_name = whitelist[field]["type"]

                if op not in allowed_ops:
                    raise ValueError(f"Operator '{op}' not allowed for '{field}'")

                try:
                    if type_name == "datetime":
                        expected_type = datetime
                    else:
                        expected_type = getattr(builtins, type_name)
                except AttributeError:
                    raise ValueError(f"Unsupported type '{type_name}' in whitelist")

                if type_name == 'datetime':
                    try:
                        if op in ("BETWEEN", "IN"):
                            f["value"] = [convert_to_unix(v) for v in value]
                        else:
                            f["value"] = convert_to_unix(value)
                    except Exception as e:
                        raise ValueError(f"Invalid date format for field '{field}': {str(e)}")

                if op in ("BETWEEN", "IN"):
                    if not isinstance(value, (list, tuple)):
                        raise ValueError(f"Operator '{op}' requires a list or tuple")
                    if not all(isinstance(v, expected_type) for v in value):
                        raise ValueError(f"All values for '{field}' must be of type '{type_name}'")
                else:
                    if not isinstance(value, expected_type):
                        raise ValueError(f"Value for '{field}' must be of type '{type_name}'")

        if aggregation:
            for alias, agg_def in aggregation.items():
                # Skip validation if field is an aggregation expression
                if is_aggregation_field(agg_def["field"]):
                    continue
                    
                if agg_def["field"] not in allowed_fields:
                    raise ValueError(f"Aggregation field '{agg_def['field']}' not allowed")
                if agg_def["function"].upper() not in ("SUM", "AVG", "COUNT", "MIN", "MAX"):
                    raise ValueError(f"Aggregation function '{agg_def['function']}' not supported")

        if group_by:
            for g in group_by:
                # Skip validation for aggregation fields in group_by
                if is_aggregation_field(g):
                    continue
                    
                if g not in allowed_fields:
                    raise ValueError(f"Group by field '{g}' not allowed")

        if having:
            for condition in having:
                aggregation_alias = condition["aggregation"]  # Direkter Zugriff auf 'aggregation'
                op = condition["op"]
                val = condition["value"]

                if aggregation_alias not in aggregation:
                    raise ValueError(f"HAVING aggregation '{aggregation_alias}' must match an aggregation alias")
                if op not in ("=", "!=", "<", "<=", ">", ">="):
                    raise ValueError(f"HAVING operator '{op}' not supported")
                if not isinstance(val, (int, float)):
                    raise ValueError("HAVING values must be numeric")

        if limit is not None and (not isinstance(limit, int) or limit <= 0):
            raise ValueError("Limit must be a positive integer")

        if offset is not None and (not isinstance(offset, int) or offset < 0):
            raise ValueError("Offset must be a non-negative integer")

def build_select_clause(fields: list[str], aggregation: Optional[Aggregation], group_by: Optional[GroupBy] = None) -> list[str]:
    select_lines = []
    
    # Handle regular fields (excluding any that are in group_by to avoid duplicates)
    if fields == ["*"]:
        select_lines.append("*")
    else:
        # Only add fields that aren't in group_by (added automatically)
        group_by_set = set(str(g) for g in group_by) if group_by else set()
        select_lines.extend(
            f"{field} AS \"{field}\"" for field in fields if field not in group_by_set
        )
    
    # Handle aggregations
    if aggregation:
        for alias, agg in aggregation.items():
            field = agg['field']
            select_lines.append(f"{agg['function'].upper()}({field}) as {alias}")
    
    return select_lines

def build_join_clause(used_fields: set[str], field_table_map: dict[str, str]) -> tuple[list[str], list[str]]:
    join_fields = {
        f for f in used_fields 
        if field_table_map.get(f) != "games" 
        and not f.startswith("games.")
    }
    join_lines = []
    additional_selects = []

    for join in join_fields:
        join_base = join.replace(".name", "")
        join_lines.append(
            f"LEFT JOIN games_{join_base} ON games.id = games_{join_base}.game_id\n"
            f"LEFT JOIN {join_base} ON games_{join_base}.{join_base}_id = {join_base}.id"
        )
        if f"{join_base}.name" not in used_fields:
            additional_selects.append(f"GROUP_CONCAT(DISTINCT {join_base}.name) AS \"{join_base}.name\"")

    return join_lines, additional_selects

def build_where_clause(filters: Filters) -> tuple[list[str], list[Union[str, int, float]]]:
    where_clauses = []
    params = []

    for f in filters:
        field = f["field"]
        op = f["op"]
        val = f["value"]

        if op == "BETWEEN":
            where_clauses.append(f"{field} BETWEEN ? AND ?")
            params.extend(val)
        elif op == "IN":
            placeholders = ", ".join(["?"] * len(val))
            where_clauses.append(f"{field} IN ({placeholders})")
            params.extend(val)
        else:
            where_clauses.append(f"{field} {op} ?")
            params.append(val)

    return where_clauses, params

def build_having_clause(having: Having) -> tuple[list[str], list[Union[int, float]]]:
    having_clauses = []
    params = []

    for condition in having:
        aggregation_alias = condition["aggregation"]  # Direkter Zugriff auf 'aggregation'
        op = condition["op"]
        val = condition["value"]
        having_clauses.append(f"{aggregation_alias} {op} ?")
        params.append(val)

    return having_clauses, params

def build_order_by_clause(sort_fields):
    """Build ORDER BY clause from processed sort fields"""
    if not sort_fields:
        return ""
    
    order_parts = []
    for sort_field in sort_fields:
        order_parts.append(f"{sort_field['field']} {'ASC' if sort_field['direction'] == 'ASC' else 'DESC'}")
    
    return f"ORDER BY {', '.join(order_parts)}"

def get_data(
    conn,
    fields: list[str],
    sort_fields: Optional[list[dict[str, str]]] = None,
    filters: Optional[Filters] = None,
    df: bool = True,
    aggregation: Optional[Aggregation] = None,
    group_by: Optional[GroupBy] = None,
    having: Optional[Having] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> Union[tuple[str, list], list[dict]]:
    """
    Executes a dynamic SQL query on the 'games' table with flexible selection, filtering,
    aggregation, grouping, sorting, limiting, and pagination.

    Args:
        conn: SQLite connection object.
        fields (list[str]): List of database fields to select.
                           Example: ["name", "release_date"] or ["*"] to select all fields.
        sort_fields (Optional[list[dict[int: str, bool]]]): List of dicts of sort fields with keys beeing the sort index.
                           Example: (0: ("release_date", True)) for ascending order,
                           or (0: ("release_date", False)) for descending order.
        filters (Optional[list[FilterCondition]]): Conditions for the WHERE clause.
                           Example: [{"field": "release_date", "op": ">", "value": 2010}].
        df (bool): If True, returns a pandas dataframe (instead of executing it and returning the dict).
        aggregation (Optional[Aggregation]): Aggregation definitions (e.g., COUNT, AVG, SUM).
                           Example:
                           {
                               "game_count": {"field": "games.id", "function": "COUNT"}
                           }
        having (Optional[Having]): Conditions on aggregated values (HAVING clause).
                           Example: [{"field": "game_count", "op": ">", "value": 10}].
        group_by (Optional[GroupBy]): List of fields to group by.
                           Example: ["genre"].
        limit (Optional[int]): Maximum number of rows to return.
        offset (Optional[int]): Number of rows to skip (for pagination).

    Returns:
        list[dict]: List of results as dictionaries (if df=False).
        tuple[str, list]: The SQL query string and corresponding parameters (if df=True).

    Example:
        aggregation = {
            "game_count": {"field": "games.id", "function": "COUNT"}
        }
        group_by = ["genre"]
        having = [{"field": "game_count", "op": ">", "value": 10}]

        results = get_data(
            cursor,
            fields=["genre"],
            aggregation=aggregation,
            group_by=group_by,
            having=having,
            sort_field=("game_count", False),
            limit=5
        )
    """
    filters = filters or []
    aggregation = aggregation or {}
    group_by = group_by or []
    sort_fields = sort_fields or []
    having = having or []
    offset = offset or 0

    validate_get_data_input(fields, sort_fields, filters, aggregation, group_by, limit, having, offset)

    aggregation_fields = {agg["field"] for agg in aggregation.values()}
    aggregation_aliases = set(aggregation.keys())

    used_fields = (
        {str(f) for f in fields}
        | {str(f['field']) for f in filters}
        | set(str(g) for g in group_by)
        | aggregation_fields
        | {str(v["field"]) for v in sort_fields}
    )

    used_fields -= aggregation_aliases

    mapping = helpers.load_mapping(config.DB_MAPPING_PATH)
    field_table_map = {e[0]: e[1] for e in mapping}
    field_table_map["languages.name"] = "languages"

    select_lines = build_select_clause(fields, aggregation, group_by)
    join_lines, join_selects = build_join_clause(used_fields, field_table_map)
    where_clauses, params = build_where_clause(filters)
    having_clauses, having_params = build_having_clause(having)
    params.extend(having_params)

    full_select = select_lines + join_selects
    sort_line = build_order_by_clause(sort_fields)

    query = f"""
    SELECT {", ".join(full_select)}
    FROM games
    {"\n".join(join_lines)}
    {"WHERE " + " AND ".join(where_clauses) if where_clauses else ""}
    {"GROUP BY " + ", ".join(group_by) if group_by else "GROUP BY games.id"}
    {"HAVING " + " AND ".join(having_clauses) if having_clauses else ""}
    {f"ORDER BY {sort_line}" if sort_line else ""}
    {f"LIMIT {limit}" if limit else ""}
    {f"OFFSET {offset}" if offset else ""}
    """

    if not df:
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            results = [dict(row) for row in cursor.fetchall()]

            with open(config.QUERY_WHITELIST_PATH, "r", encoding="utf-8") as f:
                whitelist = json.load(f)
                for row in results:
                    for field in row:
                        if field in whitelist and whitelist[field]["type"] == "datetime":
                            row[field] = convert_from_unix(row[field])
            
            return results
        except Exception as e:
            print("Failed Query:\n", query)
            print("With Params:\n", params)
            raise e
    else:
        df = pd.read_sql_query(query, conn, params=params)
        return df


