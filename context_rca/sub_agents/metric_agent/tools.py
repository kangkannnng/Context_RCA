import os
import pandas as pd
from typing import Optional, List, Tuple, Dict
from google.adk.tools.tool_context import ToolContext

PROJECT_DIR = os.getenv('PROJECT_DIR', '.')

input_timestamp_path = os.path.join(PROJECT_DIR, "input/input_timestamp.csv")
df_input_timestamp = pd.read_csv(input_timestamp_path)

df_input_timestamp = df_input_timestamp.sort_values('start_timestamp').reset_index(drop=True)

def _get_fault_period_info(df_fault_timestamps: pd.DataFrame, row_index: int) -> Tuple[List[str], str, str, str]:
    """
    获取指定行的故障时间段信息

    参数:
        df_fault_timestamps: 包含故障起止时间戳的DataFrame
        row_index: 指定要查询的行索引

    返回:
        匹配的Pod文件列表, 日期, 开始时间, 结束时间
    """
    row = df_fault_timestamps.iloc[row_index]
    date = row['date']
    start_time = row['start_timestamp']
    end_time = row['end_timestamp']

    # 构建Pod数据目录路径
    pod_dir = os.path.join(PROJECT_DIR, 'data', 'processed', f'{date}', 'metric-parquet', 'apm', 'pod')
    matching_files = os.listdir(pod_dir)

    return matching_files, date, start_time, end_time


def _extract_service_name_from_pod(pod_name: str) -> str:
    """
    从pod名称中提取service名称

    参数:
        pod_name: pod名称，如 "redis-cart-0"

    返回:
        service名称，如 "redis"
    """
    # 提取用-分割后的第一项作为服务名
    if '-' in pod_name:
        return pod_name.split('-')[0]
    return pod_name


def _get_normal_time_periods(df_fault_timestamps: pd.DataFrame, current_index: int) -> List[Tuple[str, str]]:
    """
    获取正常时间段（当前故障前后的正常时间段）

    参数:
        df_fault_timestamps: 故障时间戳DataFrame
        current_index: 当前故障索引

    返回:
        正常时间段列表 [(start_time, end_time), ...]
    """
    normal_periods = []
    current_row = df_fault_timestamps.iloc[current_index]
    current_start = current_row['start_timestamp']
    current_end = current_row['end_timestamp']

    # 获取当前故障前的正常时间段（上一个故障结束到当前故障开始）
    if current_index > 0:
        prev_row = df_fault_timestamps.iloc[current_index - 1]
        prev_end = prev_row['end_timestamp']
        # 正常时间段：上一个故障结束后10分钟 到 当前故障开始
        normal_periods.append((prev_end + 10 * 60 * 1_000_000_000, current_start))
        # normal_periods.append((prev_end , current_start))

    # 获取当前故障后的正常时间段（当前故障结束到下一个故障开始）
    if current_index < len(df_fault_timestamps) - 1:
        next_row = df_fault_timestamps.iloc[current_index + 1]
        next_start = next_row['start_timestamp']
        # 正常时间段：当前故障结束 到 下一个故障开始
        normal_periods.append((current_end + 10 * 60 * 1_000_000_000, next_start))
        # normal_periods.append((current_end , next_start))

    return normal_periods


def _get_metrics_description_from_dataframe(df_pod: pd.DataFrame, columns: List[str] = None) -> Dict[str, pd.Series]:
    """
    获取DataFrame指定列的统计描述信息

    参数:
        df_pod: Pod指标数据的DataFrame
        columns: 需要获取描述统计的列名列表，如果为None则使用数值型列

    返回:
        包含每列描述统计信息的字典
    """
    if columns is None:
        # 默认选择数值型列，这里增加了rrt_max指标
        numeric_columns = ['client_error_ratio', 'error_ratio', 'request', 'response', 'rrt', 'rrt_max', 'server_error_ratio',
                           'timeout']
        # 过滤出实际存在的列
        columns = [col for col in numeric_columns if col in df_pod.columns]

    descriptions = {}
    for column in columns:
        if column in df_pod.columns:
            # 描述统计（含 0.25、0.5、0.75、0.95、0.99）
            desc = df_pod[column].describe(percentiles=[0.25, 0.5, 0.75, 0.95, 0.99])

            # 计算非零比例
            col_data = df_pod[column].dropna()
            non_zero_ratio = (col_data != 0).sum() / len(col_data) if len(col_data) > 0 else 0
            desc['non_zero_ratio'] = round(non_zero_ratio, 3)  # 保留三位小数

            descriptions[column] = desc

    return descriptions


def _get_filtered_metrics_description_with_outlier_removal(df_pod: pd.DataFrame, start_time: str, end_time: str,
                                                          target_columns: List[str] = None,
                                                          remove_outliers: bool = False) -> Dict[str, pd.Series]:
    """
    获取指定时间范围内的指标描述统计，可选择是否移除异常值

    参数:
        df_pod: Pod指标数据的DataFrame
        start_time: 开始时间戳
        end_time: 结束时间戳
        target_columns: 需要分析的列名列表
        remove_outliers: 是否移除异常值（最小2个和最大2个值）

    返回:
        指标描述统计信息字典
    """
    if 'timestamp_ns' in df_pod.columns:
        # 将时间戳转换为整数进行比较
        start_ts = int(start_time)
        end_ts = int(end_time)
        df_filtered = df_pod[(df_pod['timestamp_ns'] >= start_ts) & (df_pod['timestamp_ns'] <= end_ts)]
    else:
        df_filtered = df_pod

    if len(df_filtered) == 0:
        return {}

    # 如果需要移除异常值且数据量足够
    if remove_outliers and len(df_filtered) > 4:  # 至少需要5个数据点才能移除4个
        return _get_metrics_description_from_dataframe_without_outliers(df_filtered, target_columns)
    else:
        return _get_metrics_description_from_dataframe(df_filtered, target_columns)


def _get_metrics_description_from_dataframe_without_outliers(df_pod: pd.DataFrame, columns: List[str] = None) -> Dict[
    str, pd.Series]:
    """
    获取DataFrame指定列的统计描述信息，移除最小2个和最大2个值

    参数:
        df_pod: Pod指标数据的DataFrame
        columns: 需要获取描述统计的列名列表，如果为None则使用数值型列

    返回:
        包含每列描述统计信息的字典
    """
    if columns is None:
        # 默认选择数值型列
        numeric_columns = ['client_error_ratio', 'error_ratio', 'request', 'response', 'rrt', 'rrt_max', 'server_error_ratio',
                           'timeout']
        # 过滤出实际存在的列
        columns = [col for col in numeric_columns if col in df_pod.columns]

    descriptions = {}
    for column in columns:
        if column in df_pod.columns:
            # 获取该列的数据并排序
            col_data = df_pod[column].dropna().sort_values()

            if len(col_data) <= 4:
                # 数据点太少，直接用原始数据描述
                desc = col_data.describe(percentiles=[0.25, 0.5, 0.75, 0.95, 0.99])
            else:
                # 去掉最小2个和最大2个
                trimmed_data = col_data.iloc[2:-2]
                desc = trimmed_data.describe(percentiles=[0.25, 0.5, 0.75, 0.95, 0.99])

            # 计算非零比例（基于去除异常值后的数据）
            non_zero_ratio = (trimmed_data != 0).sum() / len(trimmed_data) if len(col_data) > 4 else (col_data != 0).sum() / len(col_data)
            desc['non_zero_ratio'] = round(non_zero_ratio, 3)

            descriptions[column] = desc

    return descriptions


def _analyze_fault_vs_normal_metrics_by_service(df_fault_timestamps: pd.DataFrame, index: int,
                                               target_columns: List[str] = None) -> Optional[Dict]:
    """
    按Service级别分析故障时间段与正常时间段的指标对比
    结构：service → pod → metrics (normal_periods_combined, fault_period)

    参数:
        df_fault_timestamps: 故障时间戳DataFrame
        index: 要分析的故障索引
        target_columns: 需要分析的指标列名列表

    返回:
        按Service组织的包含故障和正常时间段指标对比的字典
    """
    pod_files, date, fault_start, fault_end = _get_fault_period_info(df_fault_timestamps, index)

    if not pod_files:
        return None

    normal_periods = _get_normal_time_periods(df_fault_timestamps, index)

    # 按Service → Pod → Metrics 结构组织分析结果
    service_analysis = {}

    for pod_file in pod_files:
        pod_path = os.path.join(PROJECT_DIR, 'data', 'processed', f'{date}', 'metric-parquet', 'apm', 'pod', pod_file)
        pod_name = pod_file.split('_')[1] if '_' in pod_file else pod_file.split('.')[0]
        service_name = _extract_service_name_from_pod(pod_name)

        try:
            df_pod = pd.read_parquet(pod_path)

            if len(df_pod) == 0:
                continue

            # 如果service不存在，初始化
            if service_name not in service_analysis:
                service_analysis[service_name] = {}

            # 如果pod不存在，初始化
            if pod_name not in service_analysis[service_name]:
                service_analysis[service_name][pod_name] = {
                    'normal_periods_combined': {},  # 合并的正常数据统计
                    'fault_period': {}  # 故障数据统计
                }

            # 收集所有正常时间段的数据
            all_normal_data = []

            for i, (normal_start, normal_end) in enumerate(normal_periods):
                # 过滤当前正常时间段的数据
                start_ts = int(normal_start)
                end_ts = int(normal_end)
                normal_data = df_pod[(df_pod['timestamp_ns'] >= start_ts) & (df_pod['timestamp_ns'] <= end_ts)]

                if len(normal_data) > 0:
                    all_normal_data.append(normal_data)

            # 合并所有正常时间段的数据
            if all_normal_data:
                combined_normal_data = pd.concat(all_normal_data, ignore_index=True)

                # 对合并的正常数据进行统计（移除异常值）
                if len(combined_normal_data) > 4:  # 至少需要5个数据点才能移除4个
                    normal_desc = _get_metrics_description_from_dataframe_without_outliers(combined_normal_data,
                                                                                          target_columns)
                else:
                    normal_desc = _get_metrics_description_from_dataframe(combined_normal_data, target_columns)

                service_analysis[service_name][pod_name]['normal_periods_combined'] = normal_desc

            # 2. 再获取故障时间段的统计（不移除异常值）
            fault_desc = _get_filtered_metrics_description_with_outlier_removal(
                df_pod, fault_start, fault_end, target_columns, remove_outliers=False
            )

            service_analysis[service_name][pod_name]['fault_period'] = fault_desc

        except Exception as e:
            pass

    return service_analysis if service_analysis else None


def _get_node_metrics_files_mapping(date: str) -> Dict[str, str]:
    """
    获取节点指标文件名映射，返回指标名称到文件名的映射关系

    参数:
        date: 日期，格式如 "2025-06-06"

    返回:
        指标名到文件名的映射字典
    """
    return {
        'node_cpu_usage_rate': f'infra_node_node_cpu_usage_rate_{date}.parquet',
        'node_disk_read_bytes_total': f'infra_node_node_disk_read_bytes_total_{date}.parquet',
        'node_disk_read_time_seconds_total': f'infra_node_node_disk_read_time_seconds_total_{date}.parquet',
        'node_disk_write_time_seconds_total': f'infra_node_node_disk_write_time_seconds_total_{date}.parquet',
        'node_disk_written_bytes_total': f'infra_node_node_disk_written_bytes_total_{date}.parquet',
        'node_filesystem_free_bytes': f'infra_node_node_filesystem_free_bytes_{date}.parquet',
        'node_filesystem_size_bytes': f'infra_node_node_filesystem_size_bytes_{date}.parquet',
        'node_filesystem_usage_rate': f'infra_node_node_filesystem_usage_rate_{date}.parquet',
        'node_memory_MemAvailable_bytes': f'infra_node_node_memory_MemAvailable_bytes_{date}.parquet',
        'node_memory_MemTotal_bytes': f'infra_node_node_memory_MemTotal_bytes_{date}.parquet',
        'node_memory_usage_rate': f'infra_node_node_memory_usage_rate_{date}.parquet',
        'node_network_receive_bytes_total': f'infra_node_node_network_receive_bytes_total_{date}.parquet',
        'node_network_receive_packets_total': f'infra_node_node_network_receive_packets_total_{date}.parquet',
        'node_network_transmit_bytes_total': f'infra_node_node_network_transmit_bytes_total_{date}.parquet',
        'node_network_transmit_packets_total': f'infra_node_node_network_transmit_packets_total_{date}.parquet',
        'node_sockstat_TCP_inuse': f'infra_node_node_sockstat_TCP_inuse_{date}.parquet'
    }


def _get_target_nodes() -> List[str]:
    """
    获取目标分析节点列表（只分析aiops-k8s-01到aiops-k8s-08这8个节点）

    返回:
        目标节点名称列表
    """
    return [f'aiops-k8s-{i:02d}' for i in range(1, 9)]  # aiops-k8s-01 到 aiops-k8s-08


def _load_node_metric_data(date: str, metric_name: str) -> Optional[pd.DataFrame]:
    """
    加载指定日期和指标的节点数据

    参数:
        date: 日期，格式如 "2025-06-06"
        metric_name: 指标名称，如 "node_cpu_usage_rate"

    返回:
        节点指标数据DataFrame，如果文件不存在则返回None
    """
    node_dir = os.path.join(PROJECT_DIR, 'data', 'processed', f'{date}', 'metric-parquet', 'infra', 'infra_node')

    file_mapping = _get_node_metrics_files_mapping(date)

    if metric_name not in file_mapping:
        return None

    file_path = os.path.join(node_dir, file_mapping[metric_name])

    try:
        if not os.path.exists(file_path):
            return None

        df = pd.read_parquet(file_path)

        # 只保留目标节点数据
        target_nodes = _get_target_nodes()
        df_filtered = df[df['kubernetes_node'].isin(target_nodes)]

        if len(df_filtered) == 0:
            return None

        return df_filtered

    except Exception:
        return None


def _get_node_metrics_description_with_time_filter(df_node: pd.DataFrame, start_time: str, end_time: str,
                                                  metric_column: str, remove_outliers: bool = False) -> Optional[
    pd.Series]:
    """
    获取指定时间范围内节点指标的描述统计

    参数:
        df_node: 节点指标数据DataFrame
        start_time: 开始时间戳
        end_time: 结束时间戳
        metric_column: 指标列名（实际数值列）
        remove_outliers: 是否移除异常值

    返回:
        指标描述统计信息，如果无数据则返回None
    """
    if 'timestamp_ns' not in df_node.columns:
        return None

    # 时间过滤
    start_ts = int(start_time)
    end_ts = int(end_time)
    df_filtered = df_node[(df_node['timestamp_ns'] >= start_ts) & (df_node['timestamp_ns'] <= end_ts)]

    if len(df_filtered) == 0:
        return None

    # 获取指标数据
    if metric_column not in df_filtered.columns:
        return None

    metric_data = df_filtered[metric_column].dropna()

    if len(metric_data) == 0:
        return None

    # 是否移除异常值
    if remove_outliers and len(metric_data) > 4:
        metric_data_sorted = metric_data.sort_values()
        metric_data = metric_data_sorted.iloc[2:-2]  # 去掉最小2个和最大2个
     # 描述统计 + 百分位
    desc = metric_data.describe(percentiles=[0.25, 0.5, 0.75, 0.95, 0.99])

    # **新增：非零比例**
    non_zero_ratio = (metric_data != 0).sum() / len(metric_data)
    desc['non_zero_ratio'] = round(non_zero_ratio, 3)

    return desc


def _analyze_node_metrics_by_node(df_fault_timestamps: pd.DataFrame, index: int,
                                 target_metrics: List[str] = None) -> Optional[Dict]:
    """
    分析指定故障时间段与正常时间段的节点指标对比
    结构：node → metric → {normal_periods_combined, fault_period}

    参数:
        df_fault_timestamps: 故障时间戳DataFrame
        index: 要分析的故障索引
        target_metrics: 需要分析的指标列表，如果为None则使用全部10个指标

    返回:
        按节点组织的包含故障和正常时间段指标对比的字典
    """
    if target_metrics is None:
        target_metrics = ['node_cpu_usage_rate',
                          'node_disk_read_bytes_total',
                          'node_disk_read_time_seconds_total',
                          'node_disk_write_time_seconds_total',
                          'node_disk_written_bytes_total',
                          'node_filesystem_free_bytes',
                          'node_filesystem_usage_rate',
                          'node_filesystem_usage_rate',
                          'node_memory_MemAvailable_bytes',
                          'node_memory_MemTotal_bytes',
                          'node_memory_usage_rate',
                          'node_network_receive_bytes_total',
                          'node_network_receive_packets_total',
                          'node_network_transmit_bytes_total',
                          'node_network_transmit_packets_total',
                          'node_sockstat_TCP_inuse', ]

    # 获取故障时间信息
    _, date, fault_start, fault_end = _get_fault_period_info(df_fault_timestamps, index)
    normal_periods = _get_normal_time_periods(df_fault_timestamps, index)
    target_nodes = _get_target_nodes()

    # 按 节点 → 指标 → 时间段 结构组织分析结果
    nodes_analysis = {}

    for node_name in target_nodes:
        # 初始化节点结构
        nodes_analysis[node_name] = {}

        # 为当前节点分析所有指标
        for metric_name in target_metrics:
            # 加载该指标的数据
            df_metric = _load_node_metric_data(date, metric_name)

            if df_metric is None:
                continue

            # 过滤当前节点的数据
            df_node = df_metric[df_metric['kubernetes_node'] == node_name]

            if len(df_node) == 0:
                continue

            # 初始化指标结构
            nodes_analysis[node_name][metric_name] = {
                'normal_periods_combined': None,
                'fault_period': None
            }

            # 1. 合并所有正常时间段数据进行统计
            all_normal_data = []

            for i, (normal_start, normal_end) in enumerate(normal_periods):
                start_ts = int(normal_start)
                end_ts = int(normal_end)
                normal_data = df_node[(df_node['timestamp_ns'] >= start_ts) & (df_node['timestamp_ns'] <= end_ts)]

                if len(normal_data) > 0:
                    all_normal_data.append(normal_data)

            # 合并正常时间段数据并统计
            if all_normal_data:
                combined_normal_data = pd.concat(all_normal_data, ignore_index=True)

                # 获取统计（移除异常值）
                normal_desc = _get_node_metrics_description_with_time_filter(
                    combined_normal_data,
                    str(combined_normal_data['timestamp_ns'].min()),
                    str(combined_normal_data['timestamp_ns'].max()),
                    metric_name,
                    remove_outliers=(len(combined_normal_data) > 4)
                )

                nodes_analysis[node_name][metric_name]['normal_periods_combined'] = normal_desc

            # 2. 故障时间段统计
            fault_desc = _get_node_metrics_description_with_time_filter(
                df_node, fault_start, fault_end, metric_name, remove_outliers=False
            )

            nodes_analysis[node_name][metric_name]['fault_period'] = fault_desc

    return nodes_analysis if nodes_analysis else None


# ==================== 1. Pod 指标文件映射 ====================

def _get_pod_metrics_files_mapping(date: str) -> Dict[str, str]:
    """
    获取 Pod 指标文件名映射，返回指标名称到文件名的映射关系

    参数:
        date: 日期，格式如 "2025-06-06"

    返回:
        指标名到文件名的映射字典
    """
    return {
        'pod_cpu_usage': f'infra_pod_pod_cpu_usage_{date}.parquet',
        'pod_fs_reads_bytes': f'infra_pod_pod_fs_reads_bytes_{date}.parquet',
        'pod_fs_writes_bytes': f'infra_pod_pod_fs_writes_bytes_{date}.parquet',
        'pod_memory_working_set_bytes': f'infra_pod_pod_memory_working_set_bytes_{date}.parquet',
        'pod_network_receive_bytes': f'infra_pod_pod_network_receive_bytes_{date}.parquet',
        'pod_network_receive_packets': f'infra_pod_pod_network_receive_packets_{date}.parquet',
        'pod_network_transmit_bytes': f'infra_pod_pod_network_transmit_bytes_{date}.parquet',
        'pod_network_transmit_packets': f'infra_pod_pod_network_transmit_packets_{date}.parquet',
        'pod_processes': f'infra_pod_pod_processes_{date}.parquet'
    }


# ==================== 2. 目标 Pod 列表 ====================

def _get_target_pods() -> List[str]:
    """
    获取目标分析 Pod 列表
    """
    services = [
        "adservice-0", "adservice-1", "adservice-2",
        "cartservice-0", "cartservice-1", "cartservice-2",
        "checkoutservice-0", "checkoutservice-1", "checkoutservice-2",
        "currencyservice-0", "currencyservice-1", "currencyservice-2",
        "emailservice-0", "emailservice-1", "emailservice-2",
        "frontend-0", "frontend-1", "frontend-2",
        "paymentservice-0", "paymentservice-1", "paymentservice-2",
        "productcatalogservice-0", "productcatalogservice-1", "productcatalogservice-2",
        "recommendationservice-0", "recommendationservice-1", "recommendationservice-2",
        "redis-cart-0",
        "shippingservice-0", "shippingservice-1", "shippingservice-2"
    ]
    return services


# ==================== 3. 加载 Pod 指标数据 ====================

def _load_pod_metric_data(date: str, metric_name: str) -> Optional[pd.DataFrame]:
    """
    加载指定日期和指标的 Pod 数据

    参数:
        date: 日期，格式如 "2025-06-06"
        metric_name: 指标名称，如 "pod_cpu_usage"

    返回:
        Pod 指标数据 DataFrame，如果文件不存在则返回 None
    """
    pod_dir = os.path.join(PROJECT_DIR, 'data', 'processed', f'{date}', 'metric-parquet', 'infra', 'infra_pod')

    file_mapping = _get_pod_metrics_files_mapping(date)

    if metric_name not in file_mapping:
        return None

    file_path = os.path.join(pod_dir, file_mapping[metric_name])

    try:
        if not os.path.exists(file_path):
            return None

        df = pd.read_parquet(file_path)

        # 只保留目标 pod 数据
        target_pods = _get_target_pods()
        df_filtered = df[df['pod'].isin(target_pods)]

        if len(df_filtered) == 0:
            return None

        return df_filtered

    except Exception:
        return None


# ==================== 4. 时间过滤统计 ====================

def _get_pod_metrics_description_with_time_filter(df_pod: pd.DataFrame, start_time: str, end_time: str,
                                                 metric_column: str, remove_outliers: bool = False) -> Optional[
    pd.Series]:
    """
    获取指定时间范围内 Pod 指标的描述统计
    """
    if 'timestamp_ns' not in df_pod.columns:
        return None

    # 时间过滤
    start_ts = int(start_time)
    end_ts = int(end_time)
    df_filtered = df_pod[(df_pod['timestamp_ns'] >= start_ts) & (df_pod['timestamp_ns'] <= end_ts)]

    if len(df_filtered) == 0:
        return None

    # 获取指标数据
    if metric_column not in df_filtered.columns:
        return None

    metric_data = df_filtered[metric_column].dropna()

    if len(metric_data) == 0:
        return None

    # 是否移除异常值
    if remove_outliers and len(metric_data) > 4:
        metric_data_sorted = metric_data.sort_values()
        metric_data = metric_data_sorted.iloc[2:-2]  # 去掉最小2个和最大2个
    # 生成描述统计
    desc = metric_data.describe(percentiles=[0.25, 0.5, 0.75, 0.95, 0.99])

    # 新增非零比例
    desc['non_zero_ratio'] = round((metric_data != 0).sum() / len(metric_data), 3)

    return desc


# ==================== 5. 按 Pod 分析故障 vs 正常 ====================

def _analyze_pod_metrics_by_pod(df_fault_timestamps: pd.DataFrame, index: int,
                               target_metrics: List[str] = None) -> Optional[Dict]:
    """
    分析指定故障时间段与正常时间段的 Pod 指标对比
    结构：pod → metric → {normal_periods_combined, fault_period}
    """
    if target_metrics is None:
        target_metrics = [
            'pod_cpu_usage', 'pod_fs_reads_bytes', 'pod_fs_writes_bytes',
            'pod_memory_working_set_bytes', 'pod_network_receive_bytes',
            'pod_network_receive_packets', 'pod_network_transmit_bytes',
            'pod_network_transmit_packets', 'pod_processes'
        ]

    # 获取故障时间信息
    _, date, fault_start, fault_end = _get_fault_period_info(df_fault_timestamps, index)
    normal_periods = _get_normal_time_periods(df_fault_timestamps, index)
    target_pods = _get_target_pods()

    # 按 Pod → 指标 → 时间段 结构组织分析结果
    pods_analysis = {}

    for pod_name in target_pods:
        pods_analysis[pod_name] = {}

        for metric_name in target_metrics:
            # 加载该指标的数据
            df_metric = _load_pod_metric_data(date, metric_name)

            if df_metric is None:
                continue

            # 过滤当前 Pod 的数据
            df_pod = df_metric[df_metric['pod'] == pod_name]
            # 删除 device 列为 /dev/vdb 的行
            if 'device' in df_pod.columns:
                df_pod = df_pod[df_pod['device'] != '/dev/dmb']

            if len(df_pod) == 0:
                continue

            # 初始化指标结构
            pods_analysis[pod_name][metric_name] = {
                'normal_periods_combined': None,
                'fault_period': None
            }

            # 1. 合并所有正常时间段数据
            all_normal_data = []

            for i, (normal_start, normal_end) in enumerate(normal_periods):
                start_ts = int(normal_start)
                end_ts = int(normal_end)
                normal_data = df_pod[(df_pod['timestamp_ns'] >= start_ts) & (df_pod['timestamp_ns'] <= end_ts)]

                if len(normal_data) > 0:
                    all_normal_data.append(normal_data)

            # 合并正常时间段数据并统计
            normal_desc = None
            if all_normal_data:
                combined_normal_data = pd.concat(all_normal_data, ignore_index=True)

                normal_desc = _get_pod_metrics_description_with_time_filter(
                    combined_normal_data,
                    str(combined_normal_data['timestamp_ns'].min()),
                    str(combined_normal_data['timestamp_ns'].max()),
                    metric_name,
                    remove_outliers=(len(combined_normal_data) > 4)
                )

            # 2. 故障时间段统计
            fault_desc = _get_pod_metrics_description_with_time_filter(
                df_pod, fault_start, fault_end, metric_name, remove_outliers=False
            )
            pods_analysis[pod_name][metric_name]['fault_period'] = fault_desc
            pods_analysis[pod_name][metric_name]['normal_periods_combined'] = normal_desc

    return pods_analysis if pods_analysis else None




def _convert_metrics_to_csv(metric_data: Dict, change_threshold: float = 0.05) -> tuple[str, dict]:
    """
    将指标数据转换为CSV格式，只包含显著变化的异常指标
    
    参数:
        metric_data: 原始指标数据
        change_threshold: 变化阈值（默认5%）
    
    返回:
        tuple: (csv_string, unique_dict)
            - csv_string: CSV格式的异常指标列表
            - unique_dict: 唯一值字典 {'service_name': [...], 'node_name': [...], 'pod_name': [...]}
    """
    anomaly_rows = []
    unique_services = set()
    unique_nodes = set()
    unique_pods = set()
    
    # 统计信息
    stats = {
        'service': {'total_checked': 0, 'passed_filter': 0},
        'tidb': {'total_checked': 0, 'passed_filter': 0},
        'node': {'total_checked': 0, 'passed_filter': 0},
        'pod': {'total_checked': 0, 'passed_filter': 0}
    }
    
    def calculate_symmetric_ratio(normal_val, fault_val):
        """计算对称比率"""
        return abs(fault_val - normal_val) / ((fault_val + normal_val) / 2 + 1e-9)
    
    def extract_stats(stats_dict):
        """从统计字典提取关键值"""
        if stats_dict is None:
            return None, None, None, None
        if isinstance(stats_dict, dict) and not stats_dict:
            return None, None, None, None
        return (
            stats_dict.get('50%', 0),
            stats_dict.get('99%', 0),
            stats_dict.get('25%', 0),
            stats_dict.get('75%', 0)
        )

    # Define absolute thresholds for noise filtering
    ABSOLUTE_THRESHOLDS = {
        # CPU (cores or ratio)
        'pod_cpu_usage': 0.05,
        'node_cpu_usage_rate': 0.05,
        'cpu_usage': 0.05, # TiDB
        
        # Memory (Bytes) - 10MB
        'pod_memory_working_set_bytes': 10 * 1024 * 1024,
        'node_memory_usage_rate': 0.05,
        'node_memory_MemAvailable_bytes': 100 * 1024 * 1024, # 100MB for Node
        
        # Network (Bytes/Packets)
        'pod_network_receive_bytes': 1024, # 1KB
        'pod_network_transmit_bytes': 1024,
        'pod_network_receive_packets': 10,
        'pod_network_transmit_packets': 10,
        'node_network_receive_bytes_total': 1024 * 1024, # 1MB
        'node_network_transmit_bytes_total': 1024 * 1024,
        
        # Disk (Bytes)
        'pod_fs_reads_bytes': 1024 * 1024, # 1MB
        'pod_fs_writes_bytes': 1024 * 1024,
        'node_disk_written_bytes_total': 10 * 1024 * 1024, # 10MB
        'node_disk_read_bytes_total': 10 * 1024 * 1024,
        
        # Latency (ms)
        'rrt': 10,
        'rrt_max': 10,
        'duration_99th': 10,
        'raft_apply_wait': 5,
        'raft_propose_wait': 5,
        
        # Error Ratio
        'error_ratio': 0.01,
        'server_error_ratio': 0.01,
        'client_error_ratio': 0.01,
        
        # Others
        'pod_processes': 2,
        'io_util': 0.05,
    }

    def is_negligible(metric_name, val1, val2):
        threshold = ABSOLUTE_THRESHOLDS.get(metric_name)
        if threshold is None:
            # Try partial match for generic names
            if 'cpu' in metric_name: threshold = 0.05
            elif 'memory' in metric_name and 'rate' in metric_name: threshold = 0.05
            elif 'bytes' in metric_name: threshold = 1024 * 1024 # Default 1MB
            elif 'packets' in metric_name: threshold = 10
            elif 'ratio' in metric_name: threshold = 0.01
            else: return False # No threshold defined, assume significant
            
        # If BOTH values are below threshold, it's negligible
        # Use max to be safe (if one spikes above threshold, it's not negligible)
        return max(val1, val2) < threshold
    
    # 处理 Service 指标
    for service_name, service_pods in metric_data.get('service_metrics', {}).items():
        unique_services.add(str(service_name))
        
        for pod_name, pod_metrics in service_pods.items():
            unique_pods.add(str(pod_name))
            
            normal_combined = pod_metrics.get('normal_periods_combined', {})
            fault_period = pod_metrics.get('fault_period', {})
            
            # 获取所有指标名称（从normal或fault中）
            all_metric_names = set(normal_combined.keys()) | set(fault_period.keys())
            
            for metric_name in all_metric_names:
                
                normal_stats = normal_combined.get(metric_name)
                fault_stats = fault_period.get(metric_name)
                
                if normal_stats is None or fault_stats is None:
                    continue
                if (isinstance(normal_stats, dict) and not normal_stats) or (isinstance(fault_stats, dict) and not fault_stats):
                    continue
                
                n_p50, n_p99, n_p25, n_p75 = extract_stats(normal_stats)
                f_p50, f_p99, f_p25, f_p75 = extract_stats(fault_stats)
                
                if n_p50 is None or f_p50 is None:
                    continue
                
                # Check for negligible values
                if is_negligible(metric_name, n_p99, f_p99):
                    continue
                
                p50_ratio = calculate_symmetric_ratio(n_p50, f_p50)
                p99_ratio = calculate_symmetric_ratio(n_p99, f_p99)
                
                stats['service']['total_checked'] += 1
                
                # 只保留显著变化的指标
                if p50_ratio >= change_threshold or p99_ratio >= change_threshold:
                    stats['service']['passed_filter'] += 1
                    anomaly_rows.append({
                        'metric_type': 'service',
                        'service_name': str(service_name),
                        'pod_name': str(pod_name),
                        'node_name': 'N/A',
                        'metric_name': str(metric_name),
                        'normal_median': round(n_p50, 2),
                        'fault_median': round(f_p50, 2),
                        'normal_p99': round(n_p99, 2),
                        'fault_p99': round(f_p99, 2),
                        'median_change_ratio': round(p50_ratio, 4),
                        'p99_change_ratio': round(p99_ratio, 4)
                    })
    
    # 处理 TiDB 组件指标
    for component_name, component_metrics in metric_data.get('tidb_metrics', {}).items():
        unique_services.add(str(component_name))
        
        for metric_name, metric_stats in component_metrics.items():
            normal_stats = metric_stats.get('normal_periods_combined')
            fault_stats = metric_stats.get('fault_period')
            
            if normal_stats is None or fault_stats is None:
                continue
            if (isinstance(normal_stats, dict) and not normal_stats) or (isinstance(fault_stats, dict) and not fault_stats):
                continue
            
            n_p50, n_p99, n_p25, n_p75 = extract_stats(normal_stats)
            f_p50, f_p99, f_p25, f_p75 = extract_stats(fault_stats)
            
            if n_p50 is None or f_p50 is None:
                continue
            
            # Check for negligible values
            if is_negligible(metric_name, n_p99, f_p99):
                continue
            
            p50_ratio = calculate_symmetric_ratio(n_p50, f_p50)
            p99_ratio = calculate_symmetric_ratio(n_p99, f_p99)
            
            stats['tidb']['total_checked'] += 1
            
            if p50_ratio >= change_threshold or p99_ratio >= change_threshold:
                stats['tidb']['passed_filter'] += 1
                anomaly_rows.append({
                    'metric_type': 'tidb',
                    'service_name': str(component_name),
                    'pod_name': 'N/A',
                    'node_name': 'N/A',
                    'metric_name': str(metric_name),
                    'normal_median': round(n_p50, 2),
                    'fault_median': round(f_p50, 2),
                    'normal_p99': round(n_p99, 2),
                    'fault_p99': round(f_p99, 2),
                    'median_change_ratio': round(p50_ratio, 4),
                    'p99_change_ratio': round(p99_ratio, 4)
                })
    
    # 处理 Node 指标
    node_pod_mapping = metric_data.get('node_pod_mapping', {})
    for node_name, node_metrics in metric_data.get('node_metrics', {}).items():
        unique_nodes.add(str(node_name))
        
        # 添加该节点上的所有 Pod
        pods_on_node = node_pod_mapping.get(node_name, [])
        for pod in pods_on_node:
            unique_pods.add(str(pod))
        
        for metric_name, metric_stats in node_metrics.items():
            normal_stats = metric_stats.get('normal_periods_combined')
            fault_stats = metric_stats.get('fault_period')
            
            if normal_stats is None or fault_stats is None:
                continue
            if (isinstance(normal_stats, dict) and not normal_stats) or (isinstance(fault_stats, dict) and not fault_stats):
                continue
            
            n_p50, n_p99, n_p25, n_p75 = extract_stats(normal_stats)
            f_p50, f_p99, f_p25, f_p75 = extract_stats(fault_stats)
            
            if n_p50 is None or f_p50 is None:
                continue
            
            # Check for negligible values
            if is_negligible(metric_name, n_p99, f_p99):
                continue
            
            p50_ratio = calculate_symmetric_ratio(n_p50, f_p50)
            p99_ratio = calculate_symmetric_ratio(n_p99, f_p99)
            
            # === 新增逻辑: 绝对值饱和度检查 ===
            is_saturated = False
            # 检查 Node 内存/CPU 是否过载 (假设阈值为 0.8 即 80%)
            if metric_name in ['node_memory_usage_rate', 'node_cpu_usage_rate']:
                if f_p50 > 0.8:  # 故障期间中位数超过 80%
                    is_saturated = True
            
            # 检查 Node 磁盘使用率是否过载 (假设阈值为 0.8 即 80%)
            if metric_name == 'node_filesystem_usage_rate':
                if f_p50 > 0.8:
                    is_saturated = True

            stats['node']['total_checked'] += 1
            
            if p50_ratio >= change_threshold or p99_ratio >= change_threshold or is_saturated:
                stats['node']['passed_filter'] += 1
                anomaly_rows.append({
                    'metric_type': 'node',
                    'service_name': 'N/A',
                    'pod_name': 'N/A',
                    'node_name': str(node_name),
                    'metric_name': str(metric_name),
                    'normal_median': round(n_p50, 2),
                    'fault_median': round(f_p50, 2),
                    'normal_p99': round(n_p99, 2),
                    'fault_p99': round(f_p99, 2),
                    'median_change_ratio': round(p50_ratio, 4),
                    'p99_change_ratio': round(p99_ratio, 4)
                })
    
    # 处理 Pod 指标
    for pod_name, pod_metrics in metric_data.get('pod_metrics', {}).items():
        unique_pods.add(str(pod_name))
        
        for metric_name, metric_stats in pod_metrics.items():
            normal_stats = metric_stats.get('normal_periods_combined')
            fault_stats = metric_stats.get('fault_period')
            
            # Skip if normal stats are missing (we can't compare)
            if normal_stats is None or (isinstance(normal_stats, dict) and not normal_stats):
                continue

            n_p50, n_p99, n_p25, n_p75 = extract_stats(normal_stats)
            if n_p50 is None:
                continue

            # Handle fault stats
            if fault_stats is None or (isinstance(fault_stats, dict) and not fault_stats):
                # Missing data in fault period -> Treat as 0 (Pod likely down/killed)
                f_p50 = 0.0
                f_p99 = 0.0
            else:
                f_p50, f_p99, f_p25, f_p75 = extract_stats(fault_stats)
                if f_p50 is None:
                    f_p50 = 0.0
                    f_p99 = 0.0
            
            # Check for negligible values
            if is_negligible(metric_name, n_p99, f_p99):
                continue
            
            p50_ratio = calculate_symmetric_ratio(n_p50, f_p50)
            p99_ratio = calculate_symmetric_ratio(n_p99, f_p99)
            
            stats['pod']['total_checked'] += 1
            
            if p50_ratio >= change_threshold or p99_ratio >= change_threshold:
                stats['pod']['passed_filter'] += 1
                anomaly_rows.append({
                    'metric_type': 'pod',
                    'service_name': 'N/A',
                    'pod_name': str(pod_name),
                    'node_name': 'N/A',
                    'metric_name': str(metric_name),
                    'normal_median': round(n_p50, 2),
                    'fault_median': round(f_p50, 2),
                    'normal_p99': round(n_p99, 2),
                    'fault_p99': round(f_p99, 2),
                    'median_change_ratio': round(p50_ratio, 4),
                    'p99_change_ratio': round(p99_ratio, 4)
                })
    
    # 如果没有异常，返回空
    if not anomaly_rows:
        return "", {'service_name': [], 'node_name': [], 'pod_name': []}
    
    # 转换为 DataFrame 并排序
    df_anomalies = pd.DataFrame(anomaly_rows)
    
    # 计算排序分数：结合变化率和绝对值
    # 对于资源类指标（内存、磁盘、网络、延迟），绝对值越大越重要
    # Score = max_change_ratio * sqrt(fault_p99)
    # 这样可以保证：
    # 1. 变化率很大但绝对值很小（如 Redis 5MB->35MB）的指标得分较低
    # 2. 变化率适中但绝对值很大（如 Shipping 200MB->500MB）的指标得分较高
    
    def calculate_score(row):
        ratio = max(row['median_change_ratio'], row['p99_change_ratio'])
        # Use max of normal and fault value to handle "Drop to Zero" cases correctly
        # If value drops from 1000 to 0, we want to score it based on 1000, not 0.
        value = max(row['normal_p99'], row['fault_p99'])
        
        # 对于 CPU/Processes 等小数值指标，直接用 Ratio
        if row['metric_name'] in ['pod_cpu_usage', 'pod_processes', 'node_cpu_usage_rate', 'node_memory_usage_rate', 'node_filesystem_usage_rate',
                                  'io_util', 'region_pending', 'rocksdb_write_stall', 'cpu_usage', 'failed_query_ops', 'store_down_count', 'store_unhealth_count',
                                  'raft_apply_wait', 'raft_propose_wait', 'duration_99th',
                                  'rrt', 'rrt_max', 'client_error', 'client_error_ratio', 'server_error', 'server_error_ratio', 'error', 'error_ratio',
                                  'dns', 'http.resp.status']:
            return ratio * 100  # 给予较高权重，因为这些通常是关键瓶颈
            
        # 对于 Bytes/Duration 等大数值指标，结合绝对值
        # 使用 sqrt 作为一个折中，既不完全忽略 Ratio，也不完全由 Value 主导
        
        # 针对 Bytes 类型指标，先转换为 MB (除以 1e6) 再开方，避免数值过大导致权重失衡
        if 'bytes' in row['metric_name'].lower():
             return ratio * ((value / 1e6) ** 0.5)
             
        return ratio * (value ** 0.5)

    df_anomalies['score'] = df_anomalies.apply(calculate_score, axis=1)
    df_anomalies = df_anomalies.sort_values('score', ascending=False)
    df_anomalies = df_anomalies.drop('score', axis=1)
    
    # 转换为 CSV
    csv_string = df_anomalies.to_csv(index=False)
    
    # 构建唯一值字典
    unique_dict = {
        'service_name': sorted(list(unique_services)),
        'node_name': sorted(list(unique_nodes)),
        'pod_name': sorted(list(unique_pods))
    }
    
    return csv_string, unique_dict



def _get_node_pod_mapping(date: str) -> Dict[str, List[str]]:
    """
    获取每个节点上部署的Pod列表

    参数:
        date: 日期，格式如 "2025-06-06"

    返回:
        节点到Pod列表的映射字典 {node_name: [pod1, pod2, ...]}
    """
    infra_pod_dir = os.path.join(PROJECT_DIR, 'data', 'processed', f'{date}', 'metric-parquet', 'infra', 'infra_pod')

    # 优先尝试读取CPU使用率文件
    target_file = f'infra_pod_pod_cpu_usage_{date}.parquet'
    target_file_path = os.path.join(infra_pod_dir, target_file)

    df_pod_info = None

    try:
        if os.path.exists(target_file_path):
            df_pod_info = pd.read_parquet(target_file_path)
        else:
            # 如果目标文件不存在，随机选择一个文件
            if os.path.exists(infra_pod_dir):
                available_files = [f for f in os.listdir(infra_pod_dir) if f.endswith('.parquet')]
                if available_files:
                    selected_file = available_files[0]  # 选择第一个文件
                    selected_file_path = os.path.join(infra_pod_dir, selected_file)
                    df_pod_info = pd.read_parquet(selected_file_path)
                else:
                    return {}
            else:
                return {}

        if df_pod_info is None or len(df_pod_info) == 0:
            return {}

        # 获取目标节点列表
        target_nodes = _get_target_nodes()
        node_pod_mapping = {}

        for node_name in target_nodes:
            # 筛选该节点的数据
            node_data = df_pod_info[df_pod_info['instance'] == node_name]
            if len(node_data) > 0:
                # 获取该节点上的唯一Pod列表
                pods_on_node = node_data['pod'].unique().tolist()
                node_pod_mapping[node_name] = pods_on_node
            else:
                node_pod_mapping[node_name] = []

        return node_pod_mapping

    except Exception:
        return {}


# ==================== TiDB 服务相关函数 ====================

def _get_tidb_services_files_mapping(date: str) -> Dict[str, Dict[str, str]]:
    """
    获取TiDB服务的文件名映射，返回服务名到指标文件的映射关系

    参数:
        date: 日期，格式如 "2025-06-06"

    返回:
        服务名到指标文件映射的字典 {service_name: {metric_name: file_name}}
    """
    return {
        'tidb-tidb': {
            'failed_query_ops': f'infra_tidb_failed_query_ops_{date}.parquet',
            'duration_99th': f'infra_tidb_duration_99th_{date}.parquet',
            'connection_count': f'infra_tidb_connection_count_{date}.parquet',
            'server_is_up': f'infra_tidb_server_is_up_{date}.parquet',
            'cpu_usage': f'infra_tidb_cpu_usage_{date}.parquet',
            'memory_usage': f'infra_tidb_memory_usage_{date}.parquet'
        },
        'tidb-pd': {
            'store_up_count': f'infra_pd_store_up_count_{date}.parquet',
            'store_down_count': f'infra_pd_store_down_count_{date}.parquet',
            'cpu_usage': f'infra_pd_cpu_usage_{date}.parquet',
            'memory_usage': f'infra_pd_memory_usage_{date}.parquet',
            'storage_used_ratio': f'infra_pd_storage_used_ratio_{date}.parquet',
            'store_unhealth_count': f'infra_pd_store_unhealth_count_{date}.parquet'
        },
        'tidb-tikv': {
            'cpu_usage': f'infra_tikv_cpu_usage_{date}.parquet',
            'memory_usage': f'infra_tikv_memory_usage_{date}.parquet',
            'server_is_up': f'infra_tikv_server_is_up_{date}.parquet',
            'available_size': f'infra_tikv_available_size_{date}.parquet',
            'raft_propose_wait': f'infra_tikv_raft_propose_wait_{date}.parquet',
            'raft_apply_wait': f'infra_tikv_raft_apply_wait_{date}.parquet',
            'rocksdb_write_stall': f'infra_tikv_rocksdb_write_stall_{date}.parquet',
            'io_util': f'infra_tikv_io_util_{date}.parquet',
            'region_pending': f'infra_tikv_region_pending_{date}.parquet'
        }
    }


def _get_tidb_services_directories() -> Dict[str, str]:
    """
    获取TiDB服务的数据目录映射

    返回:
        服务名到目录路径的映射字典
    """
    return {
        'tidb-tidb': 'infra/infra_tidb',
        'tidb-pd': 'other',
        'tidb-tikv': 'other'
    }


def _get_tidb_core_metrics() -> Dict[str, List[str]]:
    """
    获取TiDB服务的核心指标列表（基于您的筛选建议）

    返回:
        服务名到核心指标列表的映射字典
    """
    return {
        'tidb-tidb': [
            'failed_query_ops',  # 失败请求数 - 错误率指标
            'duration_99th',  # 99分位请求延迟 - 关键性能指标
            'connection_count',  # 连接数 - 负载指标
            'server_is_up',  # 服务存活节点数 - 可用性指标
            'cpu_usage',  # CPU使用率 - 资源饱和度
            'memory_usage'  # 内存使用量 - 资源使用
        ],
        'tidb-pd': [
            'store_up_count',  # 健康Store数量 - 集群健康度
            'store_down_count',  # Down Store数量 - 故障指标
            'store_unhealth_count',  # Unhealth Store数量 - 异常指标
            'storage_used_ratio',  # 已用容量比 - 容量指标
            'cpu_usage',  # CPU使用率 - 资源使用
            'memory_usage'  # 内存使用量 - 资源使用
        ],
        'tidb-tikv': [
            'cpu_usage',  # CPU使用率 - 资源使用
            'memory_usage',  # 内存使用量 - 资源使用
            'server_is_up',  # 服务存活节点数 - 可用性
            'available_size',  # 可用存储容量 - 容量预警
            'raft_propose_wait',  # RaftPropose等待延迟P99 - 性能指标
            'raft_apply_wait',  # RaftApply等待延迟P99 - 性能指标
            'rocksdb_write_stall',  # RocksDB写阻塞次数 - 关键异常指标
            'io_util',  # IO使用率 - 磁盘IO瓶颈
            'region_pending'  # Pending Region数量 - Raft一致性异常
        ]
    }


def _load_tidb_service_data(date: str, service_name: str, metric_name: str) -> Optional[pd.DataFrame]:
    """
    加载指定TiDB服务的指标数据

    参数:
        date: 日期，格式如 "2025-06-06"
        service_name: 服务名称，如 "tidb-tidb"
        metric_name: 指标名称，如 "cpu_usage"

    返回:
        TiDB服务指标数据DataFrame，如果文件不存在则返回None
    """

    # 获取目录映射
    directories = _get_tidb_services_directories()
    if service_name not in directories:
        return None

    # 构建数据目录路径
    data_dir = os.path.join(PROJECT_DIR, 'data', 'processed', f'{date}', 'metric-parquet', directories[service_name])

    # 获取文件映射
    file_mapping = _get_tidb_services_files_mapping(date)
    if service_name not in file_mapping or metric_name not in file_mapping[service_name]:
        return None

    file_path = os.path.join(data_dir, file_mapping[service_name][metric_name])

    try:
        if not os.path.exists(file_path):
            return None

        df = pd.read_parquet(file_path)

        if len(df) == 0:
            return None

        return df

    except Exception:
        return None


def _get_tidb_metrics_description_with_time_filter(df_tidb: pd.DataFrame, start_time: str, end_time: str,
                                                  metric_column: str, remove_outliers: bool = False) -> Optional[
    pd.Series]:
    """
    获取指定时间范围内TiDB指标的描述统计

    参数:
        df_tidb: TiDB指标数据DataFrame
        start_time: 开始时间戳
        end_time: 结束时间戳
        metric_column: 指标列名（实际数值列）
        remove_outliers: 是否移除异常值

    返回:
        指标描述统计信息，如果无数据则返回None
    """
    if 'timestamp_ns' not in df_tidb.columns:
        return None

    # 时间过滤
    start_ts = int(start_time)
    end_ts = int(end_time)
    df_filtered = df_tidb[(df_tidb['timestamp_ns'] >= start_ts) & (df_tidb['timestamp_ns'] <= end_ts)]

    if len(df_filtered) == 0:
        return None

    # 获取指标数据
    if metric_column not in df_filtered.columns:
        return None

    metric_data = df_filtered[metric_column].dropna()

    if len(metric_data) == 0:
        return None

    # 是否移除异常值
    if remove_outliers and len(metric_data) > 4:
        metric_data_sorted = metric_data.sort_values()
        metric_data = metric_data_sorted.iloc[2:-2]  # 去掉最小2个和最大2个
    desc = metric_data.describe(percentiles=[0.25, 0.5, 0.75, 0.95, 0.99])

    # 新增非零比例
    desc['non_zero_ratio'] = round((metric_data != 0).sum() / len(metric_data), 3)

    return desc


def _analyze_tidb_services_metrics(df_fault_timestamps: pd.DataFrame, index: int) -> Optional[Dict]:
    """
    分析TiDB服务在故障时间段与正常时间段的指标对比
    结构：service → metric → {normal_periods_combined, fault_period}

    参数:
        df_fault_timestamps: 故障时间戳DataFrame
        index: 要分析的故障索引

    返回:
        按TiDB服务组织的包含故障和正常时间段指标对比的字典
    """
    # 获取故障时间信息
    _, date, fault_start, fault_end = _get_fault_period_info(df_fault_timestamps, index)
    normal_periods = _get_normal_time_periods(df_fault_timestamps, index)

    # 获取TiDB服务和核心指标
    core_metrics = _get_tidb_core_metrics()

    # 按 服务 → 指标 → 时间段 结构组织分析结果
    tidb_analysis = {}

    for service_name, metrics_list in core_metrics.items():
        # 初始化服务结构
        tidb_analysis[service_name] = {}

        for metric_name in metrics_list:
            # 加载该指标的数据
            df_metric = _load_tidb_service_data(date, service_name, metric_name)

            if df_metric is None:
                continue
                continue

            # 初始化指标结构
            tidb_analysis[service_name][metric_name] = {
                'normal_periods_combined': None,
                'fault_period': None
            }

            # 1. 合并所有正常时间段数据进行统计
            all_normal_data = []

            for i, (normal_start, normal_end) in enumerate(normal_periods):
                start_ts = int(normal_start)
                end_ts = int(normal_end)
                normal_data = df_metric[(df_metric['timestamp_ns'] >= start_ts) & (df_metric['timestamp_ns'] <= end_ts)]

                if len(normal_data) > 0:
                    all_normal_data.append(normal_data)

            # 合并正常时间段数据并统计
            if all_normal_data:
                combined_normal_data = pd.concat(all_normal_data, ignore_index=True)

                # 获取统计（移除异常值）
                normal_desc = _get_tidb_metrics_description_with_time_filter(
                    combined_normal_data,
                    str(combined_normal_data['timestamp_ns'].min()),
                    str(combined_normal_data['timestamp_ns'].max()),
                    metric_name,
                    remove_outliers=(len(combined_normal_data) > 4)
                )

                tidb_analysis[service_name][metric_name]['normal_periods_combined'] = normal_desc

            # 2. 故障时间段统计
            fault_desc = _get_tidb_metrics_description_with_time_filter(
                df_metric, fault_start, fault_end, metric_name, remove_outliers=False
            )

            tidb_analysis[service_name][metric_name]['fault_period'] = fault_desc

    return tidb_analysis if tidb_analysis else None


# ==================== 核心数据获取函数 ====================

def _load_filtered_metric(df_fault_timestamps: pd.DataFrame, index: int) -> tuple[str, dict, dict]:
    """
    加载并过滤异常指标数据，只返回显著变化的指标

    参数:
        df_fault_timestamps: 故障时间戳DataFrame
        index: 要分析的故障索引

    返回:
        tuple: (anomaly_metrics_csv, unique_dict, node_pod_mapping)
            - anomaly_metrics_csv: 异常指标的CSV格式字符串，包含显著变化的指标
            - unique_dict: {'service_name': [...], 'node_name': [...], 'pod_name': [...]} 唯一值字典
            - node_pod_mapping: {node_name: [pod1, pod2, ...]} 节点到Pod的映射关系
            如果没有异常或出错则返回 (None, {}, {})
    """
    # 定义要分析的关键指标，这里增加了rrt_max指标
    service_key_metrics = ['client_error_ratio', 'error_ratio', 'request', 'response', 
                          'rrt', 'rrt_max', 'server_error_ratio', 'timeout']
    
    node_metrics_list = ['node_cpu_usage_rate', 'node_disk_read_bytes_total',
                        'node_disk_read_time_seconds_total', 'node_disk_write_time_seconds_total',
                        'node_disk_written_bytes_total', 'node_filesystem_free_bytes',
                        'node_filesystem_usage_rate', 'node_memory_MemAvailable_bytes',
                        'node_memory_MemTotal_bytes', 'node_memory_usage_rate',
                        'node_network_receive_bytes_total', 'node_network_receive_packets_total',
                        'node_network_transmit_bytes_total', 'node_network_transmit_packets_total',
                        'node_sockstat_TCP_inuse']
    
    pod_metrics_list = ['pod_cpu_usage', 'pod_fs_reads_bytes', 'pod_fs_writes_bytes',
                       'pod_memory_working_set_bytes', 'pod_network_receive_bytes',
                       'pod_network_receive_packets', 'pod_network_transmit_bytes',
                       'pod_network_transmit_packets', 'pod_processes']
    
    result = {
        'fault_info': {},
        'service_metrics': {},
        'tidb_metrics': {},
        'node_metrics': {},
        'pod_metrics': {},
        'node_pod_mapping': {}
    }
    
    try:
        # 获取故障基本信息
        row = df_fault_timestamps.iloc[index]
        fault_date = row['date']
        fault_start = row['start_timestamp']
        fault_end = row['end_timestamp']

        # Ensure minimum window of 60 seconds for metric analysis to capture data points
        # Metrics are typically scraped every 15-30s. A 1s fault window will likely have no data.
        min_duration = 60 * 1_000_000_000  # 60 seconds in nanoseconds
        if fault_end - fault_start < min_duration:
            # Extend the window to ensure we capture at least one or two scrape points
            # We extend the end time.
            fault_end = fault_start + min_duration
        
        result['fault_info'] = {
            'index': int(index),
            'date': str(fault_date),
            'start_timestamp': int(fault_start),
            'end_timestamp': int(fault_end)
        }
        
        # 收集所有数据
        service_result = _analyze_fault_vs_normal_metrics_by_service(
            df_fault_timestamps, index, service_key_metrics)
        result['service_metrics'] = service_result if service_result else {}
        
        tidb_result = _analyze_tidb_services_metrics(df_fault_timestamps, index)
        result['tidb_metrics'] = tidb_result if tidb_result else {}
        
        node_result = _analyze_node_metrics_by_node(
            df_fault_timestamps, index, node_metrics_list)
        result['node_metrics'] = node_result if node_result else {}
        
        pod_result = _analyze_pod_metrics_by_pod(
            df_fault_timestamps, index, pod_metrics_list)
        result['pod_metrics'] = pod_result if pod_result else {}
        
        node_pod_mapping = _get_node_pod_mapping(fault_date)
        result['node_pod_mapping'] = node_pod_mapping if node_pod_mapping else {}
        
        # 格式化数据为CSV格式
        anomaly_metrics_csv, unique_dict = _convert_metrics_to_csv(result)

        return anomaly_metrics_csv, unique_dict, result['node_pod_mapping']

    except Exception:
        return None, {}, {}  # 返回 None 表示出错，与空字符串（无异常）区分

def metric_analysis_tool(query: str, tool_context: ToolContext) -> dict:
    """
    根据异常描述或UUID分析系统指标数据，返回该时间段内显著变化的指标。
    
    参数:
        query: 自然语言描述的异常查询，可以是：
               - UUID (例如: "345fbe93-80")
               - 时间范围描述 (例如: "2025-06-05T16:10:02Z to 2025-06-05T16:31:02Z")
               - 异常描述的文本 (例如: "The system experienced an anomaly from 2025-06-05T16:10:02Z to 2025-06-05T16:31:02Z. Please infer the possible cause")
    
    返回:
        字典包含:
        - status: "success" 或 "error"
        - anomaly_metrics: 异常指标的CSV字符串，包含显著变化的指标（如果成功）
        - unique_entities: 包含唯一的service_name、node_name、pod_name列表
        - message: 状态信息
        - matched_anomaly: 匹配到的异常描述
    """
    global df_input_timestamp
    
    try:
        # 尝试在 input_timestamp.csv 中查找匹配的行
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
        
        # 方法3: 通过时间字符串匹配（支持时间范围）
        if matched_index is None:
            # 尝试解析时间范围（格式: "YYYY-MM-DDTHH:MM:SSZ to YYYY-MM-DDTHH:MM:SSZ"）
            import re
            time_range_pattern = r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+to\s+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)'
            time_match_obj = re.search(time_range_pattern, query)
            
            if time_match_obj:
                start_time_str = time_match_obj.group(1)  # 例如: "2025-06-05T17:10:04Z"
                end_time_str = time_match_obj.group(2)    # 例如: "2025-06-05T17:33:04Z"
                
                # 规范化时间字符串用于匹配（移除T和Z，替换为空格和+00:00）
                # "2025-06-05T17:10:04Z" -> "2025-06-05 17:10:04"
                start_normalized = start_time_str.replace('T', ' ').replace('Z', '')
                end_normalized = end_time_str.replace('T', ' ').replace('Z', '')
                
                # 在start_time_utc和end_time_utc列中查找匹配的行
                time_match = df_input_timestamp[
                    (df_input_timestamp['start_time_utc'].astype(str).str.contains(start_normalized, na=False)) &
                    (df_input_timestamp['end_time_utc'].astype(str).str.contains(end_normalized, na=False))
                ]
                
                if not time_match.empty:
                    matched_index = time_match.index[0]
                    matched_row = time_match.iloc[0]
            
            # 如果时间范围匹配失败，尝试在所有时间列中进行模糊匹配
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
        
        # 如果没有找到匹配的行
        if matched_index is None:
            result = {
                "status": "error",
                "message": f"未找到与查询 '{query}' 匹配的异常记录。请尝试使用 UUID、时间范围或异常描述中的关键词。",
                "anomaly_metrics": None,
                "unique_entities": None,
                "node_pod_mapping": None,
                "matched_anomaly": None
            }
            return result
        
        # 调用 _load_filtered_metric 获取指标数据
        anomaly_metrics_csv, metric_unique_dict, node_pod_mapping = _load_filtered_metric(df_input_timestamp, matched_index)

        if anomaly_metrics_csv is None:
            # 加载过程中出错
            result = {
                "status": "error",
                "message": f"分析metric数据时出错。UUID: {matched_row['uuid']}",
                "anomaly_metrics": None,
                "unique_entities": None,
                "node_pod_mapping": None,
                "matched_anomaly": matched_row['Anomaly Description']
            }
            return result
        
        if anomaly_metrics_csv == "":
            # 分析成功但没有检测到异常指标
            result = {
                "status": "success",
                "message": f"分析完成，未检测到异常指标。UUID: {matched_row['uuid']}",
                "anomaly_metrics": None,
                "unique_entities": metric_unique_dict,
                "node_pod_mapping": node_pod_mapping,
                "matched_anomaly": matched_row['Anomaly Description'],
                "time_range": f"{matched_row['start_time_utc']} to {matched_row['end_time_utc']}"
            }
            return result

        # 成功且有异常指标
        result = {
            "status": "success",
            "message": f"成功加载metric数据。UUID: {matched_row['uuid']}",
            "anomaly_metrics": anomaly_metrics_csv,
            "unique_entities": metric_unique_dict,
            "node_pod_mapping": node_pod_mapping,
            "matched_anomaly": matched_row['Anomaly Description'],
            "time_range": f"{matched_row['start_time_utc']} to {matched_row['end_time_utc']}"
        }

        # 存储原始结果到上下文中
        state = tool_context.state
        
        state["raw_metric_result"] = result
        state["metric_data_collected"] = True

        return result
        
    except Exception as e:
        result = {
            "status": "error",
            "message": f"Metric分析过程中出错: {str(e)}",
            "anomaly_metrics": None,
            "unique_entities": None,
            "node_pod_mapping": None,
            "matched_anomaly": None
        }
        return result