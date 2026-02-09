/**
 * 地图展示页面
 * 展示告警的空间分布和热力图
 */
import React, { useState, useEffect, useRef } from 'react';
import {
  Card,
  Form,
  Select,
  DatePicker,
  Button,
  Space,
  Spin,
  message,
  Statistic,
  Row,
  Col,
  Tag,
  List,
  Drawer,
  Image,
} from 'antd';
import {
  EnvironmentOutlined,
  HeatMapOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { getMapStatistics, getConfig, getMediaUrl } from '../services/api';
import './MapPage.css';

const { RangePicker } = DatePicker;
const { Option } = Select;

const MapPage = () => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [mapData, setMapData] = useState([]);
  const [config, setConfig] = useState(null);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [drawerVisible, setDrawerVisible] = useState(false);
  const [statistics, setStatistics] = useState({
    total: 0,
    regions: {},
    eventTypes: {},
  });

  const mapRef = useRef(null);
  const mapInstance = useRef(null);
  const markersRef = useRef([]);

  // 加载配置
  useEffect(() => {
    loadConfig();
  }, []);

  // 初始化地图
  useEffect(() => {
    if (config && window.AMap) {
      initMap();
    }
    return () => {
      // 清理地图实例
      if (mapInstance.current) {
        mapInstance.current.destroy();
      }
    };
  }, [config]);

  const loadConfig = async () => {
    try {
      const res = await getConfig();
      if (res.success) {
        setConfig(res.config);
      }
    } catch (error) {
      message.error('加载配置失败');
    }
  };

  const initMap = () => {
    if (!mapRef.current || mapInstance.current) return;

    // 创建地图实例
    const map = new window.AMap.Map(mapRef.current, {
      zoom: config?.map_zoom || 5,
      center: config?.map_center || [116.4, 39.9],
      viewMode: '3D',
      pitch: 0,
    });

    mapInstance.current = map;

    // 添加工具栏
    map.addControl(new window.AMap.ToolBar());
    map.addControl(new window.AMap.Scale());
  };

  // 加载地图数据
  const loadMapData = async (values) => {
    setLoading(true);

    try {
      const params = {
        start_time: values?.time_range?.[0]?.format('YYYY-MM-DD HH:mm:ss') || null,
        end_time: values?.time_range?.[1]?.format('YYYY-MM-DD HH:mm:ss') || null,
        event_type: values?.event_type || null,
      };

      const res = await getMapStatistics(params);

      if (res.success) {
        setMapData(res.data);
        updateMapMarkers(res.data);
        calculateStatistics(res.data);
        message.success(`加载成功，共 ${res.total} 个点位`);
      }
    } catch (error) {
      message.error('加载地图数据失败：' + error.message);
    } finally {
      setLoading(false);
    }
  };

  // 更新地图标记
  const updateMapMarkers = (data) => {
    if (!mapInstance.current) return;

    // 清除旧标记
    markersRef.current.forEach((marker) => marker.setMap(null));
    markersRef.current = [];

    // 添加新标记
    data.forEach((item) => {
      const marker = new window.AMap.Marker({
        position: [item.lon, item.lat],
        title: item.event_type,
        extData: item,
      });

      // 点击标记显示详情
      marker.on('click', () => {
        setSelectedEvent(item);
        setDrawerVisible(true);
      });

      marker.setMap(mapInstance.current);
      markersRef.current.push(marker);
    });

    // 自动调整视野
    if (data.length > 0) {
      mapInstance.current.setFitView();
    }
  };

  // 计算统计信息
  const calculateStatistics = (data) => {
    const regions = {};
    const eventTypes = {};
    let total = 0;

    data.forEach((item) => {
      total += item.count;
      regions[item.region] = (regions[item.region] || 0) + item.count;
      eventTypes[item.event_type] = (eventTypes[item.event_type] || 0) + item.count;
    });

    setStatistics({ total, regions, eventTypes });
  };

  // 重置
  const handleReset = () => {
    form.resetFields();
    setMapData([]);
    setStatistics({ total: 0, regions: {}, eventTypes: {} });
    markersRef.current.forEach((marker) => marker.setMap(null));
    markersRef.current = [];
  };

  return (
    <div className="map-page">
      {/* 筛选表单 */}
      <Card className="filter-card">
        <Form
          form={form}
          layout="inline"
          onFinish={loadMapData}
        >
          <Form.Item name="event_type" label="事件类型">
            <Select
              placeholder="选择事件类型"
              allowClear
              style={{ width: 200 }}
            >
              {config?.event_types?.map((type) => (
                <Option key={type} value={type}>
                  {type}
                </Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item name="time_range" label="时间范围">
            <RangePicker
              showTime
              format="YYYY-MM-DD HH:mm"
              placeholder={['开始时间', '结束时间']}
            />
          </Form.Item>

          <Form.Item>
            <Space>
              <Button
                type="primary"
                htmlType="submit"
                icon={<EnvironmentOutlined />}
                loading={loading}
              >
                加载数据
              </Button>
              <Button
                onClick={handleReset}
                icon={<ReloadOutlined />}
              >
                重置
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>

      {/* 统计信息 */}
      {statistics.total > 0 && (
        <Card className="stats-card">
          <Row gutter={16}>
            <Col span={8}>
              <Statistic
                title="总告警数"
                value={statistics.total}
                suffix="条"
                prefix={<HeatMapOutlined />}
              />
            </Col>
            <Col span={8}>
              <Statistic
                title="覆盖区域"
                value={Object.keys(statistics.regions).length}
                suffix="个"
              />
            </Col>
            <Col span={8}>
              <Statistic
                title="事件类型"
                value={Object.keys(statistics.eventTypes).length}
                suffix="种"
              />
            </Col>
          </Row>
        </Card>
      )}

      <Row gutter={16}>
        {/* 地图容器 */}
        <Col xs={24} lg={18}>
          <Card
            className="map-card"
            title="空间分布地图"
            extra={
              <Space>
                <Tag color="blue">标记点: {mapData.length}</Tag>
              </Space>
            }
          >
            <Spin spinning={loading}>
              <div
                ref={mapRef}
                className="map-container"
                style={{ width: '100%', height: '600px' }}
              />
            </Spin>
          </Card>
        </Col>

        {/* 区域统计 */}
        <Col xs={24} lg={6}>
          <Card title="区域分布" className="region-card">
            <List
              dataSource={Object.entries(statistics.regions).sort((a, b) => b[1] - a[1])}
              renderItem={([region, count]) => (
                <List.Item>
                  <List.Item.Meta
                    title={region}
                    description={`${count} 条告警`}
                  />
                  <div style={{ width: 60, textAlign: 'right' }}>
                    <Tag color="blue">{((count / statistics.total) * 100).toFixed(1)}%</Tag>
                  </div>
                </List.Item>
              )}
            />
          </Card>

          <Card title="事件类型" className="event-type-card" style={{ marginTop: 16 }}>
            <List
              dataSource={Object.entries(statistics.eventTypes).sort((a, b) => b[1] - a[1])}
              renderItem={([type, count]) => (
                <List.Item>
                  <List.Item.Meta
                    title={type}
                    description={`${count} 条`}
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>

      {/* 详情抽屉 */}
      <Drawer
        title="告警详情"
        placement="right"
        width={400}
        onClose={() => setDrawerVisible(false)}
        open={drawerVisible}
      >
        {selectedEvent && (
          <div>
            <p><strong>事件类型：</strong>{selectedEvent.event_type}</p>
            <p><strong>区域：</strong>{selectedEvent.region}</p>
            <p><strong>告警数量：</strong>{selectedEvent.count} 条</p>
            <p><strong>坐标：</strong>({selectedEvent.lat.toFixed(4)}, {selectedEvent.lon.toFixed(4)})</p>
          </div>
        )}
      </Drawer>
    </div>
  );
};

export default MapPage;
