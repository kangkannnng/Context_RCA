import os
import pickle
import pandas as pd
from typing import Optional
from google.adk.tools.tool_context import ToolContext

PROJECT_DIR = os.getenv('PROJECT_DIR', '.')

input_timestamp_path = os.path.join(PROJECT_DIR, "input/input_timestamp.csv")
df_input_timestamp = pd.read_csv(input_timestamp_path)

def _get_period_info(df_input_timestamp: pd.DataFrame, row_index: int) -> tuple[list[str], int, int]:
    """
    获取指定行的匹配信息
    
    参数:
        df_input_timestamp: 包含故障起止时间戳的DataFrame, df_input_timestamp = pd.read_csv('input_timestamp.csv') 文件读取后的结果
        row_index: 指定要查询的行索引
        
    返回:
        匹配的文件列表, start_time, end_time
    """
    import glob
    
    row = df_input_timestamp.iloc[row_index]
    start_time_hour = row['start_time_hour']
    start_time = row['start_timestamp']
    end_time = row['end_timestamp']

    search_pattern = os.path.join(PROJECT_DIR, 'data', 'processed', '*', 'log-parquet', f'*{start_time_hour}*')
    matching_files = glob.glob(search_pattern, recursive=True)
    
    return matching_files, start_time, end_time


def _filter_logs_by_timerange(matching_files: list[str], start_time: int, end_time: int, df_log: Optional[pd.DataFrame] = None) -> Optional[pd.DataFrame]:
    """
    根据时间范围过滤日志数据

    参数:
        matching_files: 匹配的文件路径列表
        start_time: 开始时间戳
        end_time: 结束时间戳
        df_log: 包含日志数据的DataFrame，如果为None则会尝试读取匹配的文件

    返回:
        DataFrame: 过滤后的日志数据，只包含时间范围内的行；如果没有匹配文件则返回None
    """
    import pandas as pd

    if not matching_files:
        return None

    if df_log is None:
        df_log = pd.DataFrame()
        for file in matching_files:
            temp_df = pd.read_parquet(file)
            df_log = pd.concat([df_log, temp_df])

    if 'timestamp_ns' not in df_log.columns:
        return None

    filtered_df = df_log[(df_log['timestamp_ns'] >= start_time) & (df_log['timestamp_ns'] <= end_time)]
    return filtered_df


def _filter_logs_by_error(df: Optional[pd.DataFrame], column: str = 'message') -> Optional[pd.DataFrame]:
    """
    过滤包含错误关键词的日志数据

    参数:
        df: 输入的DataFrame
        column: 要检查的列名，默认为'message'

    返回:
        DataFrame: 包含error的日志数据；如果输入为None或列不存在则返回None
    """
    if df is None:
        return None

    if column not in df.columns:
        return None

    # 扩展关键词列表
    keywords = [
        'error', 'exception', 'fail', 'warn', 'critical', 'stress', 'timeout', 'refused', 
        'gc', 'garbage', 'heap', 'latency', 
        'slow', 'backoff', 'retry', 'deadlock', 'unreachable', 'election'
    ]
    pattern = '|'.join(keywords)
    
    # 1. 初步筛选：保留包含关键词的日志
    error_logs = df[df[column].str.contains(pattern, case=False, na=False)]

    # 2. 强制去噪 (Hard Filter)：物理剔除已知干扰项
    # Redis saving 是正常行为，绝非故障；TiKV 的 INFO 日志也常被误读
    exclude_keywords = [
        'Background saving', 
        'DB saved on disk', 
        'RDB: ',
        'Background RDB',
        'diskless'
    ]
    
    if not error_logs.empty:
        exclude_pattern = '|'.join(exclude_keywords)
        error_logs = error_logs[~error_logs[column].str.contains(exclude_pattern, case=False, na=False)]
    
    return error_logs


def _filter_out_injected_errors(df: Optional[pd.DataFrame], column: str = 'message') -> Optional[pd.DataFrame]:
    """
    过滤掉注入的错误（如果有特定标记）
    目前暂时不过滤 'java' 关键词，以免误杀正常的 Java 服务日志

    参数:
        df: 输入的DataFrame
        column: 要检查的列名，默认为'message'

    返回:
        DataFrame: 过滤后的日志数据；如果输入为None或列不存在则返回None
    """
    if df is None or column not in df.columns:
        return None

    # 暂时移除对 'java' 的过滤，因为 adservice 是 Java 服务，可能会包含 java 相关的异常堆栈
    # filtered_df = df[~df[column].str.contains('java', na=False)]
    return df

    
def _filter_logs_by_columns(filtered_df: Optional[pd.DataFrame], columns: Optional[list[str]] = None) -> Optional[pd.DataFrame]:
    """
    从已过滤的日志数据中进一步筛选指定的列

    参数:
        filtered_df: 已经过时间范围过滤的DataFrame
        columns: 需要保留的列名列表，如果为None则返回所有列

    返回:
        DataFrame: 只包含指定列的数据；如果输入为None则返回None
    """
    if filtered_df is None:
        return None

    if columns is None:
        return filtered_df

    # 只保留存在的列
    valid_cols = [col for col in columns if col in filtered_df.columns]
    if not valid_cols:
        return None

    return filtered_df.loc[:, valid_cols]


def _sample_logs_by_pod(df: Optional[pd.DataFrame], group_col: str = 'k8_pod', max_samples: int = 3, random_state: int = 42) -> Optional[pd.DataFrame]:
    """
    按指定列分组并随机采样每个组的日志

    参数:
        df: 输入的DataFrame
        group_col: 用于分组的列名，默认为'k8_pod'
        max_samples: 每组最大采样数量，默认为3
        random_state: 随机种子，默认为42

    返回:
        DataFrame: 采样后的数据
    """
    if df is None:
        return None

    sampled_df = df.groupby(group_col, group_keys=False).apply(
        lambda x: x.sample(min(len(x), max_samples), random_state=random_state)
    )
    return sampled_df


def _extract_log_templates(df: Optional[pd.DataFrame], message_col: str = 'message') -> Optional[pd.DataFrame]:
    """
    从日志消息中提取模板并添加模板列

    参数:
        df: 包含日志消息的DataFrame
        message_col: 包含日志消息的列名，默认为'message'

    返回:
        DataFrame: 添加了template列的DataFrame；如果无法处理则返回原DataFrame
    """
    if df is None or len(df) == 0 or message_col not in df.columns:
        return df

    try:
        drain_model_path = os.path.join(PROJECT_DIR, 'models', 'drain', 'error_log-drain.pkl')
        if not os.path.exists(drain_model_path):
            return df

        with open(drain_model_path, 'rb') as f:
            miner = pickle.load(f, encoding='bytes')

        templates = []
        for log in df[message_col]:
            cluster = miner.match(log)
            templates.append(cluster.get_template() if cluster else None)

        df['template'] = templates
        return df

    except Exception:
        return df


def _deduplicate_pod_template_combinations(df: Optional[pd.DataFrame], pod_col: str = 'k8_pod', template_col: str = 'template') -> Optional[pd.DataFrame]:
    """
    对DataFrame按pod和模板组合进行去重，只保留每种组合的第一次出现，并添加计数列

    参数:
        df: 包含pod和模板列的DataFrame
        pod_col: pod列的名称，默认为'k8_pod'
        template_col: 模板列的名称，默认为'template'

    返回:
        DataFrame: 去重后的DataFrame，添加occurrence_count列
    """
    if df is None or len(df) == 0:
        return df

    if pod_col not in df.columns or template_col not in df.columns:
        return df

    try:
        df_copy = df.copy()
        
        # Fill None templates with a prefix of the message to avoid grouping distinct errors together
        # Use first 50 chars of message as fallback template
        mask_none = df_copy[template_col].isna() | (df_copy[template_col] == 'None')
        if 'message' in df_copy.columns:
             df_copy.loc[mask_none, template_col] = df_copy.loc[mask_none, 'message'].astype(str).str.slice(0, 50)
        else:
             df_copy[template_col] = df_copy[template_col].fillna('None')

        # 计算每种组合出现的次数
        pod_template_counts = df_copy.groupby([pod_col, template_col]).size().reset_index().rename(columns={0: 'occurrence_count'})
        pod_template_counts['occurrence_count'] = pod_template_counts['occurrence_count'].apply(
            lambda x: f"出现次数:{x}"
        )

        # 去重并合并计数
        df_deduplicated = df_copy.drop_duplicates(subset=[pod_col, template_col], keep='first')
        df_deduplicated = pd.merge(df_deduplicated, pod_template_counts, on=[pod_col, template_col], how='left')

        return df_deduplicated

    except Exception:
        return df

def _extract_service_name(pod_name: str) -> str:
    """
    从pod_name中提取service_name（如frontend-1 -> frontend）

    参数:
        pod_name: pod名称字符串，例如'frontend-1'
    返回:
        str: 提取的service_name（如'frontend'），如果无法提取则返回原始pod_name
    """
    if not isinstance(pod_name, str):
        return None
    # 取第一个'-'前的部分
    import re
    match = re.match(r'([a-zA-Z0-9]+)', pod_name)
    if match:
        return match.group(1)
    return pod_name

def _load_filtered_log(df_input_timestamp: pd.DataFrame, index: int) -> Optional[tuple[str, dict]]:
    """
    加载并过滤日志数据，返回CSV格式字符串和唯一pod/service/node列表

    参数:
        df_input_timestamp: 包含故障起止时间戳的DataFrame
        index: 要查询的行索引

    返回:
        tuple: (filtered_logs_csv, log_unique_dict)
               - filtered_logs_csv: CSV格式的过滤后日志字符串，空字符串表示分析成功但无错误日志
               - log_unique_dict: {'pod_name': [...], 'service_name': [...], 'node_name': [...]} 三项唯一值列表
               如果文件不存在或处理过程中出错则返回None
    """
    matching_files, start_time, end_time = _get_period_info(df_input_timestamp, index)

    try:
        if not matching_files:
            return None  # 文件不存在，真正的错误

        df_log = pd.read_parquet(matching_files[0])
        df_filtered_logs = _filter_logs_by_timerange(matching_files, start_time, end_time, df_log=df_log)
        if df_filtered_logs is None or len(df_filtered_logs) == 0:
            return ("", {})  # 分析成功但没有日志

        df_filtered_logs = _filter_logs_by_error(df_filtered_logs, column='message')
        if df_filtered_logs is None or len(df_filtered_logs) == 0:
            return ("", {})  # 分析成功但没有错误日志

        df_filtered_logs = _filter_logs_by_columns(filtered_df=df_filtered_logs, columns=['time_beijing', 'k8_pod', 'message', 'k8_node_name'])
        if df_filtered_logs is None or len(df_filtered_logs) == 0:
            return ("", {})  # 分析成功但过滤后无结果

        df_filtered_logs = _extract_log_templates(df_filtered_logs, message_col='message')
        if df_filtered_logs is None or len(df_filtered_logs) == 0:
            return ("", {})  # 分析成功但无模板

        df_filtered_logs = _deduplicate_pod_template_combinations(df_filtered_logs, pod_col='k8_pod', template_col='template')
        if df_filtered_logs is None or len(df_filtered_logs) == 0:
            return ("", {})  # 分析成功但去重后无结果

        # 增加service_name列
        df_filtered_logs['service_name'] = df_filtered_logs['k8_pod'].apply(_extract_service_name)
        df_filtered_logs = df_filtered_logs.rename(columns={'k8_pod': 'pod_name', 'k8_node_name': 'node_name'})

        # 选择最终列并排序
        df_filtered_logs = df_filtered_logs[['node_name', 'service_name', 'pod_name', 'message', 'occurrence_count']]
        df_filtered_logs = df_filtered_logs.sort_values(by='occurrence_count', ascending=False)

        # 过滤掉注入的java错误
        df_filtered_logs = _filter_out_injected_errors(df_filtered_logs, column='message')

        if df_filtered_logs is None or len(df_filtered_logs) == 0:
            return ("", {})  # 分析成功但过滤注入错误后无结果

        log_unique_dict = {
            'pod_name': df_filtered_logs['pod_name'].unique().tolist(),
            'service_name': df_filtered_logs['service_name'].unique().tolist(),
            'node_name': df_filtered_logs['node_name'].unique().tolist()
        }
        filtered_logs_csv = df_filtered_logs.to_csv(index=False)

        return filtered_logs_csv, log_unique_dict

    except Exception:
        return None  # 出错返回 None


def log_analysis_tool(query: str, tool_context: ToolContext) -> dict:
    """
    根据异常描述或UUID分析日志数据，返回该时间段内的错误日志和相关信息。

    参数:
        query: 自然语言描述的异常查询，可以是：
               - UUID (例如: "345fbe93-80")
               - 时间范围描述 (例如: "2025-06-05T16:10:02Z to 2025-06-05T16:31:02Z")
               - 异常描述的文本

    返回:
        字典包含:
        - status: "success" 或 "error"
        - filtered_logs: 过滤后的日志CSV字符串（如果成功）
        - unique_entities: 包含唯一的pod_name、service_name、node_name列表
        - message: 状态信息
        - matched_anomaly: 匹配到的异常描述
    """
    global df_input_timestamp

    try:
        matched_index = None
        matched_row = None

        # 方法1: 通过 UUID 精确匹配
        uuid_match = df_input_timestamp[df_input_timestamp['uuid'].str.contains(query, case=False, na=False)]
        if not uuid_match.empty:
            matched_index = uuid_match.index[0]
            matched_row = uuid_match.iloc[0]

        # 方法2: 通过 Anomaly Description 模糊匹配
        if matched_index is None:
            desc_match = df_input_timestamp[
                df_input_timestamp['Anomaly Description'].str.contains(query, case=False, na=False)
            ]
            if not desc_match.empty:
                matched_index = desc_match.index[0]
                matched_row = desc_match.iloc[0]

        # 方法3: 通过时间字符串匹配
        if matched_index is None:
            import re
            time_range_pattern = r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+to\s+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)'
            time_match_obj = re.search(time_range_pattern, query)

            if time_match_obj:
                start_normalized = time_match_obj.group(1).replace('T', ' ').replace('Z', '')
                end_normalized = time_match_obj.group(2).replace('T', ' ').replace('Z', '')

                time_match = df_input_timestamp[
                    (df_input_timestamp['start_time_utc'].astype(str).str.contains(start_normalized, na=False)) &
                    (df_input_timestamp['end_time_utc'].astype(str).str.contains(end_normalized, na=False))
                ]

                if not time_match.empty:
                    matched_index = time_match.index[0]
                    matched_row = time_match.iloc[0]

            if matched_index is None:
                time_cols = ['start_time_utc', 'end_time_utc', 'start_time_beijing', 'end_time_beijing']
                for col in time_cols:
                    time_match = df_input_timestamp[
                        df_input_timestamp[col].astype(str).str.contains(query.replace('T', ' ').replace('Z', ''), case=False, na=False)
                    ]
                    if not time_match.empty:
                        matched_index = time_match.index[0]
                        matched_row = time_match.iloc[0]
                        break

        if matched_index is None:
            result = {
                "status": "error",
                "message": f"未找到与查询 '{query}' 匹配的异常记录。",
                "filtered_logs": None,
                "unique_entities": None,
                "matched_anomaly": None
            }
            return result

        filtered_logs_csv, log_unique_dict = _load_filtered_log(df_input_timestamp, matched_index)

        if filtered_logs_csv is None:
            # 加载过程中出错
            result = {
                "status": "error",
                "message": f"加载日志数据失败。UUID: {matched_row['uuid']}",
                "filtered_logs": None,
                "unique_entities": None,
                "matched_anomaly": matched_row['Anomaly Description']
            }
            return result
        
        if filtered_logs_csv == "":
            # 分析成功但没有错误日志
            result = {
                "status": "success",
                "message": f"分析完成，未检测到错误日志。UUID: {matched_row['uuid']}",
                "filtered_logs": None,
                "unique_entities": log_unique_dict,
                "matched_anomaly": matched_row['Anomaly Description'],
                "time_range": f"{matched_row['start_time_utc']} to {matched_row['end_time_utc']}"
            }
            return result

        log_count = len(filtered_logs_csv.split('\n')) - 2 if filtered_logs_csv else 0

        # 成功且有错误日志
        result = {
            "status": "success",
            "message": f"成功加载日志数据。UUID: {matched_row['uuid']}，共 {log_count} 条错误日志",
            "filtered_logs": filtered_logs_csv,
            "unique_entities": log_unique_dict,
            "matched_anomaly": matched_row['Anomaly Description'],
            "time_range": f"{matched_row['start_time_utc']} to {matched_row['end_time_utc']}"
        }

        # 存储原始结果到上下文中
        state = tool_context.state

        state["raw_log_result"] = result
        state["log_data_collected"] = True

        return result

    except Exception as e:
        result = {
            "status": "error",
            "message": f"日志分析过程中出错: {str(e)}",
            "filtered_logs": None,
            "unique_entities": None,
            "matched_anomaly": None
        }
        return result

