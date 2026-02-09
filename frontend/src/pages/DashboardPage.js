/**
 * 数据大屏页面
 * 展示数据统计和可视化图表
 */
import React, { useState, useEffect } from 'react';
import {
  Card,
  Row,
  Col,
  Statistic,
  DatePicker,
  Space,
  Button,
  Spin,
  message,
} from 'antd';
import {
  ArrowUpOutlined,
  ArrowDownOutlined,
  ReloadOutlined,
  DashboardOutlined,
} from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import dayjs from 'dayjs';
import { getStatisticsOverview } from '../services/api';
import './DashboardPage.css';

const { RangePicker } = DatePicker;

const DashboardPage = () => {
  const [loading, setLoading] = useState(false);
  const [timeRange, setTimeRange] = useState([
    dayjs().subtract(30, 'days'),
    dayjs(),
  ]);
  const [statistics, setStatistics] = useState({
    total_events: 0,
    event_type_stats: [],
    region_stats: [],
    date_stats: [],
  });

  // 初始加载
  useEffect(() => {
    loadStatistics();
  }, []);

  // 加载统计数据
  const loadStatistics = async () => {
    setLoading(true);

    try {
      const params = {
        start_time: timeRange[0]?.format('YYYY-MM-DD HH:mm:ss'),
        end_time: timeRange[1]?.format('YYYY-MM-DD HH:mm:ss'),
      };

      const res = await getStatisticsOverview(params);

      if (res.success) {
        setStatistics(res);
        message.success('数据加载成功');
      }
    } catch (error) {
      message.error('加载统计数据失败：' + error.message);
    } finally {
      setLoading(false);
    }
  };

  // 事件类型分布图表配置
  const getEventTypeChartOption = () => {
    return {
      title: {
        text: '事件类型分布',
        left: 'center',
      },
      tooltip: {
        trigger: 'item',
        formatter: '{a} <br/>{b}: {c} ({d}%)',
      },
      legend: {
        orient: 'vertical',
        left: 'left',
      },
      series: [
        {
          name: '事件类型',
          type: 'pie',
          radius: ['40%', '70%'],
          avoidLabelOverlap: false,
          itemStyle: {
            borderRadius: 10,
            borderColor: '#fff',
            borderWidth: 2,
          },
          label: {
            show: true,
            formatter: '{b}: {c}',
          },
          emphasis: {
            label: {
              show: true,
              fontSize: 16,
              fontWeight: 'bold',
            },
          },
          data: statistics.event_type_stats.map((item) => ({
            value: item.count,
            name: item.type,
          })),
        },
      ],
    };
  };

  // 区域分布图表配置
  const getRegionChartOption = () => {
    return {
      title: {
        text: '区域分布 TOP 10',
        left: 'center',
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: {
          type: 'shadow',
        },
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
        containLabel: true,
      },
      xAxis: {
        type: 'value',
        boundaryGap: [0, 0.01],
      },
      yAxis: {
        type: 'category',
        data: statistics.region_stats.map((item) => item.region),
      },
      series: [
        {
          name: '告警数量',
          type: 'bar',
          data: statistics.region_stats.map((item) => item.count),
          itemStyle: {
            color: '#1677ff',
            borderRadius: [0, 4, 4, 0],
          },
          label: {
            show: true,
            position: 'right',
          },
        },
      ],
    };
  };

  // 时间趋势图表配置
  const getDateTrendChartOption = () => {
    const sortedData = [...statistics.date_stats].reverse();

    return {
      title: {
        text: '告警趋势（最近30天）',
        left: 'center',
      },
      tooltip: {
        trigger: 'axis',
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
        containLabel: true,
      },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: sortedData.map((item) => item.date),
        axisLabel: {
          rotate: 45,
        },
      },
      yAxis: {
        type: 'value',
      },
      series: [
        {
          name: '告警数量',
          type: 'line',
          smooth: true,
          data: sortedData.map((item) => item.count),
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                {
                  offset: 0,
                  color: 'rgba(22, 119, 255, 0.3)',
                },
                {
                  offset: 1,
                  color: 'rgba(22, 119, 255, 0.05)',
                },
              ],
            },
          },
          itemStyle: {
            color: '#1677ff',
          },
          lineStyle: {
            width: 2,
          },
        },
      ],
    };
  };

  return (
    <div className="dashboard-page">
      {/* 顶部工具栏 */}
      <Card className="toolbar-card">
        <Space>
          <RangePicker
            value={timeRange}
            onChange={setTimeRange}
            format="YYYY-MM-DD"
            placeholder={['开始日期', '结束日期']}
          />
          <Button
            type="primary"
            icon={<DashboardOutlined />}
            onClick={loadStatistics}
            loading={loading}
          >
            刷新数据
          </Button>
        </Space>
      </Card>

      <Spin spinning={loading}>
        {/* 核心指标卡片 */}
        <Row gutter={16} className="metrics-row">
          <Col xs={24} sm={12} md={6}>
            <Card className="metric-card">
              <Statistic
                title="总告警数"
                value={statistics.total_events}
                suffix="条"
                valueStyle={{ color: '#1677ff' }}
                prefix={<DashboardOutlined />}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card className="metric-card">
              <Statistic
                title="事件类型"
                value={statistics.event_type_stats.length}
                suffix="种"
                valueStyle={{ color: '#52c41a' }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card className="metric-card">
              <Statistic
                title="覆盖区域"
                value={statistics.region_stats.length}
                suffix="个"
                valueStyle={{ color: '#faad14' }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card className="metric-card">
              <Statistic
                title="日均告警"
                value={
                  statistics.date_stats.length > 0
                    ? Math.round(
                        statistics.total_events / statistics.date_stats.length
                      )
                    : 0
                }
                suffix="条/天"
                valueStyle={{ color: '#f5222d' }}
              />
            </Card>
          </Col>
        </Row>

        {/* 图表区域 */}
        <Row gutter={16} className="charts-row">
          {/* 事件类型分布 */}
          <Col xs={24} lg={12}>
            <Card className="chart-card">
              {statistics.event_type_stats.length > 0 ? (
                <ReactECharts
                  option={getEventTypeChartOption()}
                  style={{ height: '400px' }}
                  notMerge={true}
                  lazyUpdate={true}
                />
              ) : (
                <div className="empty-chart">暂无数据</div>
              )}
            </Card>
          </Col>

          {/* 区域分布 */}
          <Col xs={24} lg={12}>
            <Card className="chart-card">
              {statistics.region_stats.length > 0 ? (
                <ReactECharts
                  option={getRegionChartOption()}
                  style={{ height: '400px' }}
                  notMerge={true}
                  lazyUpdate={true}
                />
              ) : (
                <div className="empty-chart">暂无数据</div>
              )}
            </Card>
          </Col>
        </Row>

        {/* 时间趋势 */}
        <Row gutter={16} className="charts-row">
          <Col span={24}>
            <Card className="chart-card">
              {statistics.date_stats.length > 0 ? (
                <ReactECharts
                  option={getDateTrendChartOption()}
                  style={{ height: '400px' }}
                  notMerge={true}
                  lazyUpdate={true}
                />
              ) : (
                <div className="empty-chart">暂无数据</div>
              )}
            </Card>
          </Col>
        </Row>
      </Spin>
    </div>
  );
};

export default DashboardPage;
