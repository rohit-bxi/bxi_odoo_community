/** @odoo-module **/

import { Component, onWillStart, onMounted, useState, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";

class EvBatteryDashboard extends Component {
    static template = "ev_battery_dashboard.DashboardTemplate";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            kpis: {},
            charging_split: {},
            charts: {},
            vehicles: [],
            vehicle_summary: [],
            fleet_overview: {},
            fleet_comparison: { labels: [], soh: [], efficiency: [], imbalance: [], resistance: [] },
            map_data: { points: [], is_route: false },
            selected_vehicle_id: "",
            selected_date_range: "all",
            selected_charge_type: "all",
            selected_soh_status: "all",
            loaded: false,
            active_tab: "dashboard",
        });

        // Refs for Chart canvases and Map container
        this.sohChartRef = useRef("sohChart");
        this.efficiencyChartRef = useRef("efficiencyChart");
        this.chargeChartRef = useRef("chargeChart");
        this.tempChartRef = useRef("tempChart");
        this.mapContainerRef = useRef("mapContainer");

        // Refs for Advanced Cell Health Charts
        this.imbalanceChartRef = useRef("imbalanceChart");
        this.regenChartRef = useRef("regenChart");
        this.resistanceChartRef = useRef("resistanceChart");

        // Keep track of Chart.js & Leaflet Map instances to destroy/recreate cleanly
        this.charts = {};
        this.mapInstance = null;

        // Dynamic Leaflet Loader Helper
        const loadLeaflet = () => {
            return new Promise((resolve) => {
                if (window.L) {
                    resolve();
                    return;
                }
                // Add Leaflet CSS
                const link = document.createElement("link");
                link.rel = "stylesheet";
                link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
                document.head.appendChild(link);

                // Add Leaflet JS
                const script = document.createElement("script");
                script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
                script.onload = () => resolve();
                document.head.appendChild(script);
            });
        };

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await loadLeaflet();
            await this.loadData();
            this.state.loaded = true;
        });

        onMounted(() => {
            this.renderTabContents();
        });
    }

    async loadData() {
        const vehicle_id = this.state.selected_vehicle_id ? parseInt(this.state.selected_vehicle_id) : null;
        const result = await this.orm.call(
            "ev.battery.log",
            "get_dashboard_data",
            [],
            {
                vehicle_id: vehicle_id,
                date_range: this.state.selected_date_range,
                charge_type: this.state.selected_charge_type,
                soh_status: this.state.selected_soh_status,
            }
        );

        this.state.kpis = result.kpis || {};
        this.state.charging_split = result.charging_split || {};
        this.state.charts = result.charts || {};
        this.state.vehicles = result.vehicles || [];
        this.state.vehicle_summary = result.vehicle_summary || [];
        this.state.fleet_overview = result.fleet_overview || {};
        this.state.fleet_comparison = result.fleet_comparison || { labels: [], soh: [], efficiency: [], imbalance: [], resistance: [] };
        this.state.map_data = result.map_data || { points: [], is_route: false };
    }

    async onVehicleChange(ev) {
        this.state.selected_vehicle_id = ev.target.value;
        await this.loadData();
        this.renderTabContents();
    }

    async onDateRangeChange(ev) {
        this.state.selected_date_range = ev.target.value;
        await this.loadData();
        this.renderTabContents();
    }

    async onChargeTypeChange(ev) {
        this.state.selected_charge_type = ev.target.value;
        await this.loadData();
        this.renderTabContents();
    }

    async onSohStatusChange(ev) {
        this.state.selected_soh_status = ev.target.value;
        await this.loadData();
        this.renderTabContents();
    }

    changeTab(tabName) {
        this.state.active_tab = tabName;
        // Small delay to allow OWL DOM updates before canvas rendering
        setTimeout(() => {
            this.renderTabContents();
        }, 100);
    }

    renderTabContents() {
        if (!this.state.loaded) return;
        
        if (this.state.active_tab === "dashboard") {
            this.renderAllCharts();
        } else if (this.state.active_tab === "cell_health") {
            this.renderCellHealthCharts();
        } else if (this.state.active_tab === "tracking") {
            this.renderMap();
        }
    }

    async openImportWizard() {
        await this.action.doAction({
            type: "ir.actions.act_window",
            name: "Import Fleet / Device Data",
            res_model: "ev.import.wizard",
            view_mode: "form",
            views: [[false, "form"]],
            target: "new",
        });
    }

    async refreshData() {
        this.state.loaded = false;
        await this.loadData();
        this.renderTabContents();
        this.state.loaded = true;
    }

    renderAllCharts() {
        this.renderSohChart();
        this.renderEfficiencyChart();
        this.renderChargeChart();
        this.renderTempChart();
    }

    renderCellHealthCharts() {
        this.renderImbalanceChart();
        this.renderRegenChart();
        this.renderResistanceChart();
    }

    renderMap() {
        const container = this.mapContainerRef.el;
        if (!container || !window.L) return;

        // Clear existing map instance
        if (this.mapInstance) {
            this.mapInstance.remove();
            this.mapInstance = null;
        }

        const mapData = this.state.map_data || {};
        const points = mapData.points || [];
        const stops = mapData.stops || [];

        // Center on Mumbai default coordinates
        const defaultCenter = [19.2843, 72.8893];
        const defaultZoom = 12;

        this.mapInstance = L.map(container).setView(defaultCenter, defaultZoom);

        // OpenStreetMap Tile Layer
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors'
        }).addTo(this.mapInstance);

        if (points.length === 0) return;

        if (mapData.is_route) {
            // Plot vehicle path (route tracking)
            const pathCoords = points.map(p => [p.lat, p.lng]);
            const polyline = L.polyline(pathCoords, {
                color: '#3b82f6',
                weight: 5,
                opacity: 0.85
            }).addTo(this.mapInstance);

            // Add start marker
            const start = points[0];
            L.marker([start.lat, start.lng]).addTo(this.mapInstance)
                .bindPopup(`🚀 <b>Route Start Point</b><br/>Time: ${start.time}<br/>Speed: ${start.speed} km/h`);

            // Add end marker
            const end = points[points.length - 1];
            L.marker([end.lat, end.lng]).addTo(this.mapInstance)
                .bindPopup(`🏁 <b>Latest Location</b><br/>Time: ${end.time}<br/>Speed: ${end.speed} km/h<br/>Ignition: ${end.ign ? 'ON' : 'OFF'}`)
                .openPopup();

            // Add stop & ignition markers
            stops.forEach(stop => {
                const color = stop.type === 'ignition_off' ? '#ef4444' : '#f59e0b';
                const emoji = stop.type === 'ignition_off' ? '🔌' : '🛑';
                L.circleMarker([stop.lat, stop.lng], {
                    radius: 8,
                    fillColor: color,
                    color: '#fff',
                    weight: 2,
                    opacity: 1,
                    fillOpacity: 0.95
                }).addTo(this.mapInstance)
                .bindPopup(`<b>${emoji} ${stop.type === 'ignition_off' ? 'Device/Ignition OFF' : 'Idle Stop'}</b><br/>
                           Time: ${stop.time}<br/>
                           Duration: ${stop.duration} mins<br/>
                           <i>${stop.description}</i>`);
            });

            // Zoom to fit route
            this.mapInstance.fitBounds(polyline.getBounds(), { padding: [40, 40] });
        } else {
            // Plot all fleet vehicles
            const markerGroup = [];
            points.forEach(p => {
                const marker = L.marker([p.lat, p.lng]).addTo(this.mapInstance)
                    .bindPopup(`⚡ <b>${p.veh_name}</b> (${p.plate})<br/>
                               Last GPS Ping: ${p.time}<br/>
                               Speed: ${p.speed} km/h<br/>
                               Ignition: ${p.ign ? 'ON' : 'OFF'}`);
                markerGroup.push([p.lat, p.lng]);
            });

            if (markerGroup.length > 0) {
                if (markerGroup.length === 1) {
                    this.mapInstance.setView(markerGroup[0], 14);
                } else {
                    this.mapInstance.fitBounds(markerGroup, { padding: [50, 50] });
                }
            }
        }
    }


    renderSohChart() {
        const ctx = this.sohChartRef.el;
        if (!ctx) return;

        if (this.charts.soh) {
            this.charts.soh.destroy();
        }

        const isVehicleFiltered = !!this.state.selected_vehicle_id;

        if (!isVehicleFiltered && this.state.fleet_comparison && this.state.fleet_comparison.labels.length) {
            // Fleet level comparative bar chart
            this.charts.soh = new Chart(ctx, {
                type: "bar",
                data: {
                    labels: this.state.fleet_comparison.labels,
                    datasets: [
                        {
                            label: "Latest Battery SOH (%)",
                            data: this.state.fleet_comparison.soh,
                            backgroundColor: this.state.fleet_comparison.soh.map(v =>
                                v >= 90 ? "rgba(16, 185, 129, 0.85)" : v >= 80 ? "rgba(245, 158, 11, 0.85)" : "rgba(239, 68, 68, 0.85)"
                            ),
                            borderColor: this.state.fleet_comparison.soh.map(v =>
                                v >= 90 ? "#10b981" : v >= 80 ? "#f59e0b" : "#ef4444"
                            ),
                            borderWidth: 1.5,
                            borderRadius: 6,
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: { callbacks: { label: ctx => ` SOH: ${ctx.parsed.y}%` } }
                    },
                    scales: {
                        y: {
                            min: 60,
                            max: 100,
                            title: { display: true, text: "State of Health (%)" }
                        }
                    }
                }
            });
            return;
        }

        // Timeline
        this.charts.soh = new Chart(ctx, {
            type: "line",
            data: {
                labels: this.state.charts.dates,
                datasets: [
                    {
                        label: "State of Health (SOH %)",
                        data: this.state.charts.soh,
                        borderColor: "#4a6cf7",
                        backgroundColor: "rgba(74, 108, 247, 0.1)",
                        fill: true,
                        tension: 0.3,
                        yAxisID: "y",
                        pointRadius: 4,
                        pointHoverRadius: 7,
                    },
                    {
                        label: "Degradation Rate (%/10k km)",
                        data: this.state.charts.degradation,
                        borderColor: "#f59e0b",
                        backgroundColor: "transparent",
                        borderDash: [5, 5],
                        tension: 0.3,
                        yAxisID: "y1",
                        pointRadius: 3,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "top" },
                    tooltip: { mode: "index", intersect: false },
                },
                scales: {
                    y: {
                        type: "linear",
                        display: true,
                        position: "left",
                        title: { display: true, text: "SOH (%)" },
                        min: 70,
                        max: 102,
                    },
                    y1: {
                        type: "linear",
                        display: true,
                        position: "right",
                        title: { display: true, text: "Degradation Rate" },
                        grid: { drawOnChartArea: false },
                        min: 0,
                        max: 1,
                    }
                }
            }
        });
    }

    renderEfficiencyChart() {
        const ctx = this.efficiencyChartRef.el;
        if (!ctx) return;

        if (this.charts.efficiency) {
            this.charts.efficiency.destroy();
        }

        const isVehicleFiltered = !!this.state.selected_vehicle_id;

        if (!isVehicleFiltered && this.state.fleet_comparison && this.state.fleet_comparison.labels.length) {
            // Fleet comparative bar chart
            this.charts.efficiency = new Chart(ctx, {
                type: "bar",
                data: {
                    labels: this.state.fleet_comparison.labels,
                    datasets: [
                        {
                            label: "Average Energy Efficiency (kWh/km)",
                            data: this.state.fleet_comparison.efficiency,
                            backgroundColor: this.state.fleet_comparison.efficiency.map(v =>
                                v > 0.19 ? "rgba(239, 68, 68, 0.85)" : v > 0.16 ? "rgba(245, 158, 11, 0.85)" : "rgba(16, 185, 129, 0.85)"
                            ),
                            borderRadius: 6,
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: { callbacks: { label: ctx => ` Avg: ${ctx.parsed.y.toFixed(3)} kWh/km` } }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            title: { display: true, text: "Efficiency (kWh/km)" }
                        }
                    }
                }
            });
            return;
        }

        // Timeline
        this.charts.efficiency = new Chart(ctx, {
            type: "bar",
            data: {
                labels: this.state.charts.dates,
                datasets: [
                    {
                        label: "Energy Efficiency (kWh/km)",
                        data: this.state.charts.efficiency,
                        backgroundColor: this.state.charts.efficiency
                            ? this.state.charts.efficiency.map(v =>
                                v > 0.19 ? "#ef4444" : v > 0.16 ? "#f59e0b" : "#10b981")
                            : "#10b981",
                        borderRadius: 5,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: ctx => `${ctx.parsed.y.toFixed(3)} kWh/km` } },
                },
                scales: {
                    y: {
                        beginAtZero: false,
                        title: { display: true, text: "Efficiency (kWh/km)" }
                    }
                }
            }
        });
    }

    renderChargeChart() {
        const ctx = this.chargeChartRef.el;
        if (!ctx) return;

        if (this.charts.charge) {
            this.charts.charge.destroy();
        }

        const data = this.state.charging_split;
        const total = (data.fast || 0) + (data.slow || 0) + (data.none || 0);
        this.charts.charge = new Chart(ctx, {
            type: "doughnut",
            data: {
                labels: ["Fast Charge (DC)", "Slow Charge (AC)", "Discharge Only"],
                datasets: [
                    {
                        data: [data.fast || 0, data.slow || 0, data.none || 0],
                        backgroundColor: ["#ef4444", "#3b82f6", "#94a3b8"],
                        hoverOffset: 8,
                        borderWidth: 2,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: {
                        callbacks: {
                            label: ctx => {
                                const pct = total ? ((ctx.parsed / total) * 100).toFixed(1) : 0;
                                return ` ${ctx.label}: ${ctx.parsed} sessions (${pct}%)`;
                            }
                        }
                    }
                }
            }
        });
    }

    renderTempChart() {
        const ctx = this.tempChartRef.el;
        if (!ctx) return;

        if (this.charts.temp) {
            this.charts.temp.destroy();
        }

        this.charts.temp = new Chart(ctx, {
            type: "line",
            data: {
                labels: this.state.charts.dates,
                datasets: [
                    {
                        label: "Average Temp (°C)",
                        data: this.state.charts.temp_avg,
                        borderColor: "#10b981",
                        backgroundColor: "rgba(16, 185, 129, 0.08)",
                        fill: true,
                        tension: 0.2,
                        pointRadius: 4,
                    },
                    {
                        label: "Maximum Temp (°C)",
                        data: this.state.charts.temp_max,
                        borderColor: "#ef4444",
                        backgroundColor: "rgba(239, 68, 68, 0.06)",
                        fill: true,
                        tension: 0.2,
                        borderDash: [4, 4],
                        pointRadius: 4,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "top" },
                    tooltip: { mode: "index", intersect: false },
                },
                scales: {
                    y: {
                        title: { display: true, text: "Temperature (°C)" },
                        suggestedMin: 15,
                    }
                }
            }
        });
    }

    // ── Advanced Cell Health Charts ──────────────────────────────────────────
    renderImbalanceChart() {
        const ctx = this.imbalanceChartRef.el;
        if (!ctx) return;

        if (this.charts.imbalance) {
            this.charts.imbalance.destroy();
        }

        const isVehicleFiltered = !!this.state.selected_vehicle_id;

        if (!isVehicleFiltered && this.state.fleet_comparison && this.state.fleet_comparison.labels.length) {
            // Fleet comparative imbalance bar chart
            this.charts.imbalance = new Chart(ctx, {
                type: "bar",
                data: {
                    labels: this.state.fleet_comparison.labels,
                    datasets: [
                        {
                            label: "Average Cell Imbalance (mV)",
                            data: this.state.fleet_comparison.imbalance,
                            backgroundColor: "rgba(244, 63, 94, 0.85)",
                            borderRadius: 6,
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: { callbacks: { label: ctx => ` Imbalance: ${ctx.parsed.y.toFixed(1)} mV` } }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            title: { display: true, text: "Imbalance (mV)" }
                        }
                    }
                }
            });
            return;
        }

        // Timeline
        this.charts.imbalance = new Chart(ctx, {
            type: "line",
            data: {
                labels: this.state.charts.dates,
                datasets: [
                    {
                        label: "Cell Imbalance (mV)",
                        data: this.state.charts.imbalance,
                        borderColor: "#f43f5e",
                        backgroundColor: "rgba(244, 63, 94, 0.08)",
                        fill: true,
                        tension: 0.2,
                        pointRadius: 4,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: ctx => `Imbalance: ${ctx.parsed.y.toFixed(1)} mV` } }
                },
                scales: {
                    y: {
                        title: { display: true, text: "Voltage Delta (mV)" },
                        suggestedMin: 0,
                    }
                }
            }
        });
    }

    renderRegenChart() {
        const ctx = this.regenChartRef.el;
        if (!ctx) return;

        if (this.charts.regen) {
            this.charts.regen.destroy();
        }

        this.charts.regen = new Chart(ctx, {
            type: "bar",
            data: {
                labels: this.state.charts.dates,
                datasets: [
                    {
                        label: "Regen Efficiency (%)",
                        data: this.state.charts.regen,
                        backgroundColor: "#10b981",
                        borderRadius: 6,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: ctx => `Recovered: ${ctx.parsed.y.toFixed(1)}%` } }
                },
                scales: {
                    y: {
                        title: { display: true, text: "Regen Efficiency (%)" },
                        min: 0,
                        max: 40,
                    }
                }
            }
        });
    }

    renderResistanceChart() {
        const ctx = this.resistanceChartRef.el;
        if (!ctx) return;

        if (this.charts.resistance) {
            this.charts.resistance.destroy();
        }

        const isVehicleFiltered = !!this.state.selected_vehicle_id;

        if (!isVehicleFiltered && this.state.fleet_comparison && this.state.fleet_comparison.labels.length) {
            // Fleet comparative resistance bar chart
            this.charts.resistance = new Chart(ctx, {
                type: "bar",
                data: {
                    labels: this.state.fleet_comparison.labels,
                    datasets: [
                        {
                            label: "Average Pack Resistance (mΩ)",
                            data: this.state.fleet_comparison.resistance,
                            backgroundColor: "rgba(139, 92, 246, 0.85)",
                            borderRadius: 6,
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: { callbacks: { label: ctx => ` Resistance: ${ctx.parsed.y.toFixed(1)} mΩ` } }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            title: { display: true, text: "Resistance (mΩ)" }
                        }
                    }
                }
            });
            return;
        }

        // Timeline
        this.charts.resistance = new Chart(ctx, {
            type: "line",
            data: {
                labels: this.state.charts.dates,
                datasets: [
                    {
                        label: "Pack Internal Resistance (mΩ)",
                        data: this.state.charts.resistance,
                        borderColor: "#8b5cf6",
                        backgroundColor: "rgba(139, 92, 246, 0.08)",
                        fill: true,
                        tension: 0.2,
                        pointRadius: 4,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: ctx => `Resistance: ${ctx.parsed.y.toFixed(1)} mΩ` } }
                },
                scales: {
                    y: {
                        title: { display: true, text: "Resistance (mΩ)" },
                        suggestedMin: 10,
                    }
                }
            }
        });
    }
}

registry.category("actions").add("ev_battery_dashboard_tag", EvBatteryDashboard);
export { EvBatteryDashboard };
