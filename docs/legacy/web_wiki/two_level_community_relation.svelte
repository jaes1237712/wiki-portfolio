<script lang="ts">
// #region Import Module
  import { Datepicker } from "flowbite-svelte";
  import { enhance } from '$app/forms'; // Import enhance if you want progressive enhancement later
  import { onMount } from 'svelte';
  import { ToggleGroup } from "bits-ui";
  import {Button} from "bits-ui";
  import cytoscape from 'cytoscape';
  import * as d3 from 'd3';
  import { format, isValid } from 'date-fns';
  import Chart from 'chart.js/auto';
  import { postPageviews, fetchNodeContent, fetchTopologySubgraphCytoscapeGraphDatas} from '$lib/api';
  import { Tabs, TabItem } from "flowbite-svelte";
  import * as chartJS from '$lib/charts/chartJS';
  import { postAnomaly } from '$lib/api';
  import { ChevronUp, ChevronDown, PanelLeft, PanelRight , PanelTop} from "@lucide/svelte";
  import { gsap } from 'gsap';
  import {Draggable} from 'gsap/Draggable';
  gsap.registerPlugin(Draggable);
// #endregion

// #region ImportType
  import type { NodeGraph, EdgeGraph, GraphData, PageviewsData, NodeContent } from '$lib/types';
  import { PageviewsDataStore } from '$lib/types/pageviews';
  import type {PageProps} from './$types';
  import type { Core } from 'cytoscape';

// #endregion

// #region initial lET something
  let {data, form}: PageProps = $props(); // Access the 'form' prop for action results
  let cy_relation: Core  | null = $state(null);
  let cy_relationContainer: HTMLDivElement | null = $state(null);
  let cy_subgraph: Core & { panzoom?: () => void;} | null = $state(null);
  let cy_subgraphContainer: HTMLDivElement | null = $state(null);
  let error = $state<string | null>(null);
  let errorDetail = $state<string | null>(null);
  let shownNodes = $state<NodeGraph[]>([]);
  let shownEdges = $state<EdgeGraph[]>([]);
  const allSubgraphNodes = $derived(data.allSubgraphNodes);
// #region 啟動畫面和渲染cytoscape
  let isDataReady = $state(false);

  $effect(() => {
      isDataReady = !!data && !!data.relationGraphData;
  });

  onMount(async () => {
      if (!isDataReady) return;
      try {
          // 只在瀏覽器端註冊 plugin
          if (typeof window !== 'undefined') {
              const panzoom = (await import('cytoscape-panzoom')).default;
              if (!(cytoscape as any).__panzoom_registered) {
                  cytoscape.use(panzoom);
                  (cytoscape as any).__panzoom_registered = true;
              }
          }
          shownNodes = data.relationGraphData.nodes;
          shownEdges = data.relationGraphData.edges;
          console.log("shownEdges",$state.snapshot(shownEdges));
          console.log("shownNodes",$state.snapshot(shownNodes));
          cy_relation = renderRelationGraph(shownNodes, shownEdges, cy_relation, cy_relationContainer) ?? null;
      } catch (e: any) {
          error = '無法載入社群圖資料';
          errorDetail = e?.message || e;
          console.error(e);
      }
  });

  function renderRelationGraph(nodesInput: NodeGraph[], edgesInput: EdgeGraph[], cy: Core & { panzoom?: () => void;}|null, cyContainer: HTMLDivElement|null) {
      if (cy) cy.destroy();
      
      const nodes = nodesInput.filter((n: NodeGraph) => n.idx !== undefined && n.pagerank !== undefined);
      const edges = edgesInput.filter((e: EdgeGraph) => e.sourceIdx !== undefined && e.targetIdx !== undefined && e.connectionsNum !== undefined);

      if (nodes.length === 0) {
          if (cyContainer) cyContainer.innerHTML = 'No data to display.'; // Optional: clear or show message
          return;
      }

      const minSize = 10, maxSize = 50;
      const pageranks = nodes.map(n => n.pagerank).filter((f): f is number => typeof f === 'number');
      const minPagerank = pageranks.length > 0 ? Math.min(...pageranks) : 0;
      const maxPagerank = pageranks.length > 0 ? Math.max(...pageranks) : (minPagerank + 1); // Ensure maxPagerank > minPagerank if all pageranks are same
      
      // 1. 先計算 log(connectionsNum + 1) 的 min/max
      
      const minLog = Math.min(...edges.map((e: EdgeGraph) => e.logConnectionsNum ?? 0));
      const maxLog = Math.max(...edges.map((e: EdgeGraph) => e.logConnectionsNum ?? 0));


      cy = cytoscape({
          container: cyContainer,
          elements: [
              ...nodes.map((n: NodeGraph) => ({
                  group: 'nodes' as 'nodes',
                  data: {
                      id: n.idx.toString(),
                      idx: n.idx,
                      title: n.title ?? '',
                      community: n.community ?? null,
                      pagerank: n.pagerank ?? minPagerank,
                      betweenness: n.betweenness ?? null,
                      authority: n.authority ?? null,
                      hub: n.hub ?? null,
                      averagePageviews: n.averagePageviews ?? null
                  }
              })),
              ...edges.map((e: EdgeGraph) => ({
                  group: 'edges' as 'edges',
                  data: {
                      id: `${e.sourceIdx}->${e.targetIdx}`,
                      source: e.sourceIdx,
                      target: e.targetIdx,
                      connectionsNum: e.connectionsNum,
                      logConnectionsNum: Math.log1p(e.connectionsNum ?? 0),
                      betweenness: e.betweenness ?? null,
                  }
              }))
          ],
          wheelSensitivity: 4,
          style: [
              {
                  selector: 'node[pagerank]',
                  style: {
                      'label': 'data(title)',
                      'background-color': '#03fffb',
                      'color': 'black',
                      'text-valign': 'center',
                      'text-halign': 'center',
                      'width': 'mapData(pagerank, ' + minPagerank + ', ' + maxPagerank + ', ' + minSize + ', ' + maxSize + ')',
                      'height': 'mapData(pagerank, ' + minPagerank + ', ' + maxPagerank + ', ' + minSize + ', ' + maxSize + ')',
                      'font-size': 'mapData(pagerank, ' + minPagerank + ', ' + maxPagerank + ', 5, 10)',
                      'text-max-width': 'mapData(pagerank, ' + minPagerank + ', ' + maxPagerank + ', ' + minSize + ', ' + maxSize + ')',
                      'text-wrap': 'wrap',
                      'font-family': 'DFKai-SB'
                  }
              },
              {
                selector: 'node.clicked',
                style: {
                  'border-width': 'mapData(pagerank, ' + minPagerank + ', ' + maxPagerank + ', 1, 4)',
                  'border-color': '#FF4136'
                }
              },
              {
                  selector: 'edge',
                  style: {
                    'events':'no',
                      'width': 'mapData(logConnectionsNum, ' + minLog + ', ' + maxLog + ', 1, 8)',
                      'line-color': '#FF4136',
                      'opacity': 'mapData(logConnectionsNum, ' + minLog + ', ' + maxLog + ', 0.4, 1)',
                      'target-arrow-color': '#FF4136',
                      'target-arrow-shape': 'triangle'
                  } as any
              },
              {
                  selector: 'edge.highlighted',
                  style: {
                      'line-color': '#febb14',
                      'target-arrow-color': '#febb14'
                  }
              },
              {
                  selector: 'node.highlighted',
                  style: {
                      'background-color': '#fefe14'
                  }
              }
          ],
          layout:{
              name: 'cose',
              // numIter: 10,
              // refresh: 5,
              animate: false,
              nodeRepulsion: (node) => {
                  const pagerank = node.data('pagerank') ?? 0;
                  return d3.scaleLinear().domain([minPagerank, maxPagerank]).range([200000, 480000])(pagerank);
              },
              edgeElasticity: (edge) => {
                return 32;
                  // const logConnectionsNum = edge.data('logConnectionsNum') ?? 0;
                  // return d3.scaleLinear().domain([minLog, maxLog]).range([16, 32])(logConnectionsNum);
              },
              gravity: 0.7
          },
          boxSelectionEnabled: true,
          selectionType: 'additive',
      }) as Core & { panzoom?: () => void; };

      // 註冊 panzoom
      cy.panzoom?.();
      // 點擊節點
      cy.on('tap', 'node', (evt) => {

          const node = evt.target;
          cy.nodes().removeClass('clicked');
          cy.nodes().removeClass('highlighted');
          cy.edges().removeClass('highlighted');
          node.addClass('clicked');
          const outgoingEdges = node.outgoers('edge');
          const incomingEdges = node.incomers('edge');
          outgoingEdges.addClass('highlighted');
          incomingEdges.addClass('highlighted');
          outgoingEdges.targets().addClass('highlighted');
          incomingEdges.sources().addClass('highlighted');
          // 設定 lastActiveNodeGraph

          lastActiveNodeGraph = {
            idx: node.data('idx'),
            title: node.data('title'),
            pagerank: node.data('pagerank'),
            community: node.data('community'),
            betweenness: node.data('betweenness'),
            authority: node.data('authority'),
            hub: node.data('hub'),
            averagePageviews: node.data('averagePageviews')
          } satisfies NodeGraph;
          
      });

      cy.on('tap', (evt) => {
          if (evt.target === cy) {
              cy.nodes().removeClass('clicked');
              cy.nodes().removeClass('highlighted');
              cy.edges().removeClass('highlighted');
          }
      });
      if (cy) {
        return cy;
      }
  }

  function renderSubgraph(nodesInput: NodeGraph[], edgesInput: EdgeGraph[], cy: Core & { panzoom?: () => void;}|null, cyContainer: HTMLDivElement|null) {
      if (cy) cy.destroy();
      
      const nodes = nodesInput.filter((n: NodeGraph) => n.idx !== undefined && n.pagerank !== undefined);
      const edges = edgesInput;

      if (nodes.length === 0) {
          if (cyContainer) cyContainer.innerHTML = 'No data to display.'; // Optional: clear or show message
          return;
      }

      const minSize = 10, maxSize = 50;
      const pageranks = nodes.map(n => n.pagerank).filter((f): f is number => typeof f === 'number');
      const minPagerank = pageranks.length > 0 ? Math.min(...pageranks) : 0;
      const maxPagerank = pageranks.length > 0 ? Math.max(...pageranks) : (minPagerank + 1); // Ensure maxPagerank > minPagerank if all pageranks are same
      
      // 1. 先計算 edge betweenness 的 min/max
      
      const minBetweenness  = Math.min(...edges.map((e: EdgeGraph) => e.betweenness ?? 0));
      const maxBetweenness = Math.max(...edges.map((e: EdgeGraph) => e.betweenness ?? 0));


      cy = cytoscape({
          container: cyContainer,
          elements: [
              ...nodes.map((n: NodeGraph) => ({
                  group: 'nodes' as 'nodes',
                  data: {
                      id: n.idx.toString(),
                      idx: n.idx,
                      title: n.title ?? '',
                      community: n.community ?? null,
                      pagerank: n.pagerank ?? minPagerank,
                      betweenness: n.betweenness ?? null,
                      authority: n.authority ?? null,
                      hub: n.hub ?? null,
                      averagePageviews: n.averagePageviews ?? null
                  }
              })),
              ...edges.map((e: EdgeGraph) => ({
                  group: 'edges' as 'edges',
                  data: {
                      id: `${e.sourceidx}->${e.targetidx}`,
                      source: e.sourceidx,
                      target: e.targetidx,
                      betweenness: e.betweenness ?? 0
                  }
              }))
          ],
          wheelSensitivity: 4,
          style: [
              {
                  selector: 'node[pagerank]',
                  style: {
                      'label': 'data(title)',
                      'background-color': '#03fffb',
                      'color': 'black',
                      'text-valign': 'center',
                      'text-halign': 'center',
                      'width': 'mapData(pagerank, ' + minPagerank + ', ' + maxPagerank + ', ' + minSize + ', ' + maxSize + ')',
                      'height': 'mapData(pagerank, ' + minPagerank + ', ' + maxPagerank + ', ' + minSize + ', ' + maxSize + ')',
                      'font-size': 'mapData(pagerank, ' + minPagerank + ', ' + maxPagerank + ', 5, 10)',
                      'text-max-width': 'mapData(pagerank, ' + minPagerank + ', ' + maxPagerank + ', ' + minSize + ', ' + maxSize + ')',
                      'text-wrap': 'wrap',
                      'font-family': 'DFKai-SB'
                  }
              },
              {
                selector: 'node.clicked',
                style: {
                  'border-width': 'mapData(pagerank, ' + minPagerank + ', ' + maxPagerank + ', 1, 4)',
                  'border-color': '#FF4136'
                }
              },
              {
                  selector: 'edge',
                  style: {
                    'events':'no',
                      'width': 'mapData(betweenness, ' + minBetweenness + ', ' + maxBetweenness + ', 1, 8)',
                      'line-color': '#FF4136',
                      'opacity': 'mapData(betweenness, ' + minBetweenness + ', ' + maxBetweenness + ', 0.4, 1)',
                      'target-arrow-color': '#FF4136',
                      'target-arrow-shape': 'triangle'
                  } as any
              },
              {
                  selector: 'edge.highlighted',
                  style: {
                      'line-color': '#febb14',
                      'target-arrow-color': '#febb14'
                  }
              },
              {
                  selector: 'node.highlighted',
                  style: {
                      'background-color': '#fefe14'
                  }
              }
          ],
          layout:{
              name: 'cose',
              animate: false
              // nodeRepulsion: (node) => {
              //     const betweenness = node.data('betweenness') ?? 0;
              //     return d3.scaleLinear().domain([minBetweenness, maxBetweenness]).range([20000, 48000])(betweenness);
              // },
              // edgeElasticity: (edge) => {
              //   return 32;
              // },
              // gravity: 0.7
          },
          boxSelectionEnabled: true,
          selectionType: 'additive',
      }) as Core & { panzoom?: () => void; };

      // 註冊 panzoom
      cy.panzoom?.();
      // 點擊節點
      cy.on('tap', 'node', (evt) => {

          const node = evt.target;
          cy.nodes().removeClass('clicked');
          cy.nodes().removeClass('highlighted');
          cy.edges().removeClass('highlighted');
          node.addClass('clicked');
          const outgoingEdges = node.outgoers('edge');
          const incomingEdges = node.incomers('edge');
          outgoingEdges.addClass('highlighted');
          incomingEdges.addClass('highlighted');
          outgoingEdges.targets().addClass('highlighted');
          incomingEdges.sources().addClass('highlighted');
          // 設定 lastActiveNodeGraph

          fetchNodeContent(node.data('idx')).then(content => lastActiveNodeContent = content);
          postPageviews([node.data('idx')], 'daily',
          format(lastActiveNodeChartStartDate, 'yyyy-MM-dd'), 
          format(lastActiveNodeChartEndDate, 'yyyy-MM-dd')).then(pageviewsDataStore => lastActiveNodePageviews = pageviewsDataStore[node.data('idx')]);
          
      });

      cy.on('tap', (evt) => {
          if (evt.target === cy) {
              cy.nodes().removeClass('clicked');
              cy.nodes().removeClass('highlighted');
              cy.edges().removeClass('highlighted');
          }
      });
  }
// #endregion

// #region 所有關於lastActiveNode驅動的元件
  // 由lastActiveNode驅動的state
    let lastActiveNodeGraph = $state<NodeGraph>(data.defaultRelationNodeGraph);
    let lastActiveNodeChartStartDate = $state<Date>(new Date('2025-04-01'));
    let lastActiveNodeChartEndDate = $state<Date>(new Date('2025-04-30'));
  // #endregion
  // #region Properties
    let lastActiveNodeContent: NodeContent = $state(data.defaultRelationNodeContent);
    $effect(() => {
      if (lastActiveNodeGraph === null || lastActiveNodeGraph.idx === null) lastActiveNodeContent = data.defaultRelationNodeContent;
      else {
        fetchNodeContent(lastActiveNodeGraph.idx).then(content => lastActiveNodeContent = content);
      }
    });
    let lastActiveNodePageviews: PageviewsData | null = $state(data.defaultRelationNodePageviews);
    
    $effect(() => {
        // 只有當節點真正改變時才重新獲取數據，初始化時使用預設數據
          console.log("改變lastActiveNodePageviews");
          postPageviews([lastActiveNodeGraph.idx], 'daily',
            format(lastActiveNodeChartStartDate, 'yyyy-MM-dd'), 
            format(lastActiveNodeChartEndDate, 'yyyy-MM-dd'),fetch).then(pageviewsDataStore => {
              const pageviews = pageviewsDataStore[lastActiveNodeGraph.idx].pageviews;
              lastActiveNodePageviews = {
                title:lastActiveNodeContent?.title ?? '',
                idx:lastActiveNodeGraph.idx,
                pageviews:pageviews} satisfies PageviewsData;
            });
          
          
    });
    //當lastActiveNodePageviews改變時，更新lastActiveNodeChartContainer
    let lastActiveNodeChartContainer = $state<HTMLDivElement | null>(null);
    $effect(() => {
        if (lastActiveNodeChartContainer && lastActiveNodePageviews) {
            chartJS.renderChart({
              datasets: {
                data: lastActiveNodePageviews,
                label: lastActiveNodeContent?.title ?? '',
            }, 
            container: lastActiveNodeChartContainer
          });
        }
    }); 
  // #endregion
  // #region Community
    let lastActiveCommunityChartContainer = $state<HTMLDivElement | null>(null);
    let lastActiveCommunityChartStartDate = $state<Date>(new Date('2025-04-01'));
    let lastActiveCommunityChartEndDate = $state<Date>(new Date('2025-04-30'));
    let lastActiveCommunity: number|null = $derived(data.defaultCommunity);
    let lastActiveCommunityNodeGraphs: NodeGraph[] = $derived(data.defaultCommunityNodeGraphs);
    let lastActiveCommunityPageviewsDataStore: PageviewsDataStore = new PageviewsDataStore(data.defaultCommunityPageviews);
    $effect( () => {
      if (lastActiveCommunity && lastActiveCommunityChartContainer) {
        postPageviews(lastActiveCommunityNodeGraphs.map(n => n.idx), 'daily',
        format(lastActiveCommunityChartStartDate, 'yyyy-MM-dd'), 
        format(lastActiveCommunityChartEndDate, 'yyyy-MM-dd'),fetch).then(
          pageviewsDataStore => {
            lastActiveCommunityPageviewsDataStore = new PageviewsDataStore(pageviewsDataStore);
            if(lastActiveCommunityChartContainer) {
              console.log("render chart");
              chartJS.renderChart({
                datasets: {
                  data: lastActiveCommunityPageviewsDataStore.toMergedPageviewsData(),
                  label: 'Community'+lastActiveNodeContent.title,
            }, 
            container: lastActiveCommunityChartContainer
          });
          }
        });
      }
    });

    
  // #endregion
  // #region Subgraph
    let subgraphData = $state<GraphData|null>(data.defaultRelationSubgraphData);
    // let subgraphNodes = $state<NodeGraph[]>(data.defaultRelationSubgraphData.nodes);
    // let subgraphEdges = $state<EdgeGraph[]>(data.defaultRelationSubgraphData.edges);
    $effect(() => {
      if (shownNodes.length > 0 &&  lastActiveNodeGraph.community) {
        fetchTopologySubgraphCytoscapeGraphDatas(lastActiveNodeGraph.community ?? 0, lastActiveNodeGraph.idx ?? 0).then(data => {
          subgraphData = data;
          if (subgraphData) {
            renderSubgraph(subgraphData.nodes, subgraphData.edges, cy_subgraph, cy_subgraphContainer);
          }
        });
      }
    });
  // #endregion
  

// #region 所有改變lastActiveNode的原件
  //#region VectorSearching
  let vectorSearching = $state(false);
  let searchResults = $state<{idx: number; title: string; community: number; similarity: number}[]>([]);
  $effect(()=>{
    searchResults = form?.searchResults ?? [];
  });
  //#endregion
  // #region Anomaly Detection
    let anomalyStartDate = $state<Date>(new Date('2025-04-01'));
    let anomalyEndDate = $state<Date>(new Date('2025-04-30'));
    let anomalyIdxs = $state<number[]>(data.relationGraphData.nodes.map((n: NodeGraph) => n.idx));
    let anomalyPageviewsDataStore = $state<PageviewsDataStore|null>(null);
    let anomalyLoading = $state(false);
    $effect(() => {
      if (anomalyStartDate && anomalyEndDate && (anomalyStartDate < anomalyEndDate)) {
        anomalyLoading = true;
        postAnomaly(
          anomalyIdxs, 
          format(anomalyStartDate, 'yyyy-MM-dd'), 
          format(anomalyEndDate, 'yyyy-MM-dd')
        ).then(resp => {
          anomalyPageviewsDataStore = resp satisfies PageviewsDataStore;
          console.log("AnomalyPageviewsDataStore",$state.snapshot(anomalyPageviewsDataStore));
          const pageviewDatas = Object.values(anomalyPageviewsDataStore ?? {});
          console.log("PageviewDatas",pageviewDatas);
          const pageviews = pageviewDatas.map(data => data.pageviews);
          console.log("Pageviews",pageviews);
        }).catch(err => {
          console.error(err);
          anomalyLoading = false;
        }).finally(() => {
          anomalyLoading = false;
        });
      }
    });
  
  function handleRowClick(result: {title: string}) {
        // Find the corresponding node in shownNodes using the title
        const clickedNode = allSubgraphNodes.find((node: NodeGraph) => node.title === result.title);
        // console.log("clickedNode",clickedNode);
        if (clickedNode) {
            lastActiveNodeGraph = clickedNode;
            const node = shownNodes.find((n: NodeGraph) => n.community === lastActiveNodeGraph.community);
            // console.log("zoom_node",zoom_node);
            console.log("cy_relation",cy_relation!==null);
            if (cy_relation!==null && lastActiveNodeGraph) {
              
              if (node) {
                const zoom_node = cy_relation.getElementById(node.idx.toString());
                cy_relation.zoom(1.5);
                cy_relation.center(zoom_node);
                cy_relation.nodes().removeClass('clicked');
                cy_relation.nodes().removeClass('highlighted');
                cy_relation.edges().removeClass('highlighted');
                zoom_node.addClass('clicked');
                const outgoingEdges = zoom_node.outgoers('edge');
                const incomingEdges = zoom_node.incomers('edge');
                outgoingEdges.addClass('highlighted');
                incomingEdges.addClass('highlighted');
                outgoingEdges.targets().addClass('highlighted');
                incomingEdges.sources().addClass('highlighted');
              }
            }
        } else {
            console.warn(`Node with title "${result.title}" not found in shownNodes.`);
        }
  }
  // #endregion

  // #region Anomaly Table
  interface RowData{
    title: string;
    date: string;
    pageviews: number;
    zscore: number;
  }

  // 將PageviewsDataStore轉成table方便作用的RowData
  const normalizedData = $derived.by<RowData[]>(() => {
    const data: RowData[] = [];
    if(!anomalyPageviewsDataStore) return [];
    
    for (const pageviewsData of Object.values(anomalyPageviewsDataStore)) {
      for (const date of Object.keys(pageviewsData.pageviews)){
        data.push({
          title: pageviewsData.title,
          date: date,
          pageviews: pageviewsData.pageviews[date],
          zscore: Math.round(pageviewsData.zscore?.[date] * 10000) / 10000 || 0 // 四捨五入到小數點後四位
        });
      }
    }
    return data;
  });

  type SortColumn = 'title' | 'date' | 'pageviews' | 'zscore';
  type SortDirection = 'asc' | 'desc';

  let sortColumn = $state<SortColumn>('date');
  let sortDirection = $state<SortDirection>('asc');

  function handelSort(column: SortColumn){
    if(sortColumn === column){
      if(sortDirection === 'asc'){
        sortDirection = 'desc';
      }
      else sortDirection = 'asc';
    } else{
      sortColumn = column
      sortDirection = 'asc'
    }
    currentPage = 1
  }

  // 根據排序狀態計算數據
  const sortedData = $derived.by(() => {
    if(!sortColumn || !normalizedData.length) return normalizedData;
    const sorted = [...normalizedData].sort((a, b) => {
      const valA = a[sortColumn];
      const valB = b[sortColumn];

      if (sortColumn === 'date'){
        const dateA = new Date(valA);
        const dateB = new Date(valB);
        if (!isValid(dateA) || !isValid(dateB)) return 0;
        return sortDirection === 'asc' ? dateA.getTime() - dateB.getTime() : dateB.getTime() - dateA.getTime();
      } else if(sortColumn === 'pageviews' || sortColumn === 'zscore') {
        const numA = typeof valA === 'number' ? valA : parseFloat(valA);
        const numB = typeof valB === 'number' ? valB : parseFloat(valB);
        return sortDirection === 'asc' ? numA - numB : numB - numA;
      } else {
        // For string columns like 'title'
        return sortDirection === 'asc' ? String(valA).localeCompare(String(valB)) : String(valB).localeCompare(String(valA));
      }
      return 0; 
    });
    return sorted
  });

  // #region 分頁邏輯
  let itemsPerPage = $state<number>(8);
  let currentPage = $state<number>(1);
  const paginatedData = $derived.by<RowData[]>(() => {
    const startIndex = (currentPage - 1) * itemsPerPage;
    const endIndex = startIndex + itemsPerPage;
    return sortedData.slice(startIndex, endIndex);
  });
  const totalPages = $derived.by<number>(() => {
    return Math.ceil(sortedData.length / itemsPerPage);
  });

  function goToPage(page: number) {
    if (page >= 1 && page <= totalPages) {
      currentPage = page;
    }
  }
  const canGoPrev = $derived.by<boolean>(() => {
    return currentPage > 1;
  });
  const canGoNext = $derived.by<boolean>(() => {
    return currentPage < totalPages;
  });
  // #endregion
// #endregion

// #region Draggable Resizing
  const MIN_COL_WIDTH_VW = 5; 
  const DIVIDER_WIDTH_PX = 8;
  const initialLeftWidth = 24.5;
  const initialRightWidth = 24.5;
  const initialRelationGraphWidth = 24.5;
  const initialSubgraphWidth = 24.5;
  let startDragLeftWidth = $state<number>(initialLeftWidth);
  let startDragRightWidth = $state<number>(initialRightWidth);
  let startDragRelationGraphWidth = $state<number>(initialRelationGraphWidth);
  let startDragSubgraphWidth = $state<number>(initialSubgraphWidth);
  let leftWidth = $state<number>(initialLeftWidth);
  let rightWidth = $state<number>(initialRightWidth);
  let relationGraphWidth = $state<number>(initialRelationGraphWidth);
  let subgraphWidth = $state<number>(initialSubgraphWidth);


  let isLeftPanelVisible = $derived.by<boolean>(() => {
    return leftWidth > MIN_COL_WIDTH_VW;
  });
  let isRelationGraphPanelVisible = $derived.by<boolean>(() => {
    return relationGraphWidth > MIN_COL_WIDTH_VW;
  });
  let isRightPanelVisible = $derived.by<boolean>(() => {
    return rightWidth > MIN_COL_WIDTH_VW;
  });
  let isSubgraphPanelVisible = $derived.by<boolean>(() => {
    return subgraphWidth > MIN_COL_WIDTH_VW;
  });

  function drag(options:Draggable.Vars){
    return (element: HTMLElement) => {
      Draggable.create(element, {
        ...options,
        properties:"",
      });
    }
  }
  function pxToVw(px: number){
  return (px / window.innerWidth) * 100;

  function vwToPx(vw: number){
    return (vw / 100) * window.innerWidth;
  }
}
// #endregion




</script>




{#if error}
<div class="text-red-500">{error}</div>
{#if errorDetail}
  <pre class="text-xs text-gray-500">{errorDetail}</pre>
{/if}

{:else if isDataReady}
<!-- 主容器 -->
<div class="relative grid  gap-x-2 h-screen w-screen bg-gray-600 box-border overflow-hidden"
style="grid-template-columns: {leftWidth}vw {relationGraphWidth}vw {subgraphWidth}vw {rightWidth}vw;">
  <!-- 篩選面板 --> 
  <div class="h-full grid-cols-start-1 flex flex-col overflow-hidden transition-opacity duration-300"
  style="opacity: {isLeftPanelVisible ? 1 : 0};">
    <!-- Tab Bar -->
     {#if isLeftPanelVisible}
     <Tabs>
      <TabItem open={true} title="Vector Search" >
        <!-- Use SvelteKit's form action -->
        <form method="POST" 
        action="?/vector_search"
        use:enhance={() => {
          vectorSearching = true;
          return async ({update}) => {
            await update();
            vectorSearching = false;
          };
        }}
          > 
            <label for="default-input" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">向量搜尋</label>
              <div class="relative">
              <div class="absolute inset-y-0 start-0 flex items-center ps-3 pointer-events-none">
                <svg class="w-4 h-4 text-gray-500 dark:text-gray-400" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 20 20">
                    <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m19 19-4-4m0-7A7 7 0 1 1 1 8a7 7 0 0 1 14 0Z"/>
                </svg>
              </div> 
              <input type="search" id="vector_search" 
              class="placeholder:text-gray-500 placeholder:italic 
              bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg
                focus:ring-blue-500 focus:border-blue-500 
                block w-full p-2.5 ps-10
                dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-blue-500 dark:focus:border-blue-500"
              name="searchQuery"
              value = {form?.searchQuery ?? ''}
              disabled={vectorSearching}
              required
              autocomplete="off"
              placeholder="有哪些關於氣候變遷的資訊?"
              >
          </div>
          {#if form?.missing} <!-- Display validation error -->
                <p class="text-red-500 text-sm">請輸入搜尋關鍵字</p>
            {/if}
            {#if form?.searchError} <!-- Display backend error -->
                <p class="text-red-500 text-sm">{form.searchError}</p>
            {/if}
        </form>
        <!-- Display Search Results Table -->
        <div class="w-full flex flex-col flex-grow overflow-hidden">
          <h3 class="text-lg font-semibold text-white mb-2 px-2">搜尋結果</h3>
            <!-- Implement Table here -->
            <div class="flex-grow overflow-y-auto rounded bg-gray-100">
              <table class="w-full h-full table-fixed text-sm text-left text-gray-500 bg-gray-100">
                <thead class="uppercase text-gray-950 bg-gray-200">
                  <tr>
                    <th scope="col" class="w-1/2 px-6 py-3">標題</th>
                    <th scope="col" class="w-1/4 px-6 py-3">平均日流量</th>
                    <th scope="col" class="w-1/4 px-6 py-3">相似度</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-gray-200 bg-white">
                  <!-- 搜尋狀態 -->
                  {#if vectorSearching}
                    {#each Array(10) as _}
                    <tr class="bg-gray-50 hover:bg-gray-200 cursor-pointer animate-pulse">
                      <td class="w-1/2 px-6 py-4 font-medium text-gray-900 overflow-hidden text-ellipsis">標題產生搜尋中...</td>
                        <td class="w-1/4 px-6 py-4">123</td>
                        <td class="w-1/4 px-6 py-4">0.5421</td>
                      </tr>
                    {/each}
                  <!-- 實際結果 -->
                  {:else}
                  {#each form?.searchResults as result}
                  <tr class="bg-gray-50 hover:bg-gray-200 cursor-pointer" onclick={() => handleRowClick({title: result.title})}>
                    <td class="w-1/2 px-6 py-4 font-medium text-gray-900 overflow-hidden text-ellipsis">{result.title}</td>
                      <td class="w-1/4 px-6 py-4">{result.average_pageviews}</td>
                      <td class="w-1/4 px-6 py-4">{result.similarity.toFixed(4)}</td>
                    </tr>
                  {/each}
                  {/if}
                </tbody>
              </table>
            </div>

        </div>
      </TabItem>
      <TabItem title="Anomaly Detection">
        <div class="grid grid-cols-2 gap-2">
          <Datepicker bind:value={anomalyStartDate} />
          <Datepicker bind:value={anomalyEndDate} />
        </div>
        <!-- Display Anomaly Results Table -->
        <div class="w-full h-full">
          <h3 class="text-lg font-semibold text-white mb-2 px-2">搜尋結果</h3>
            <!-- Implement Table here -->
            <div class="flex-grow overflow-y-auto rounded bg-gray-100">
              <table class="table-fixed w-full text-left">
                <thead class=" text-gray-950 bg-gray-200">
                  <tr>
                    <!-- 標題欄位 -->
                    <th scope="col" class="w-7/20 px-6 py-3 cursor-pointer select-none" onclick={() => handelSort('title')}>
                      <div class= "flex items-center gap-1">
                        標題
                        {#if sortColumn === 'title'}
                          {#if sortDirection === 'asc'}
                            <ChevronUp class="w-4 h-4" />
                          {:else}
                            <ChevronDown class="w-4 h-4" />
                          {/if}
                        {:else}
                          <ChevronUp class="w-4 h-4 opacity-50" />
                        {/if}
                      </div>
                    </th>
                    <th scope="col" class="w-5/20 px-6 py-3 cursor-pointer select-none" onclick={() => handelSort('date')}>
                      <div class= "flex items-center gap-1">
                        日期
                        {#if sortColumn === 'date'}
                          {#if sortDirection === 'asc'}
                            <ChevronUp class="w-4 h-4" />
                          {:else}
                            <ChevronDown class="w-4 h-4" />
                          {/if}
                        {:else}
                          <ChevronUp class="w-4 h-4 opacity-50" />
                        {/if}
                      </div>
                    </th>
                    <th scope="col" class="w-2/10 px-3 py-3 cursor-pointer select-none" onclick={() => handelSort('pageviews')}>
                      <div class= "flex items-center gap-1">
                        瀏覽量
                        {#if sortColumn === 'pageviews'}
                          {#if sortDirection === 'asc'}
                            <ChevronUp class="w-4 h-4" />
                          {:else}
                            <ChevronDown class="w-4 h-4" />
                          {/if}
                        {:else}
                          <ChevronUp class="w-4 h-4 opacity-50" />
                        {/if}
                      </div>
                    </th>
                    <th scope="col" class="w-2/10 px-3 py-3 cursor-pointer select-none" onclick={() => handelSort('zscore')}>
                      <div class= "flex items-center gap-1">
                        Z分數
                        {#if sortColumn === 'zscore'}
                          {#if sortDirection === 'asc'}
                            <ChevronUp class="w-4 h-4" />
                          {:else}
                            <ChevronDown class="w-4 h-4" />
                          {/if}
                        {:else}
                          <ChevronUp class="w-4 h-4 opacity-50" />
                        {/if}
                      </div>
                    </th>
                  </tr>
                </thead>
                <tbody >
                  <!-- 搜尋狀態(骨架) -->
                  {#if anomalyLoading}
                    {#each Array(itemsPerPage) as _ }
                      <tr class="bg-gray-50 hover:bg-gray-200 cursor-pointer animate-pulse">
                        <td class="w-1/2 px-6 py-4 font-medium text-gray-900 overflow-hidden text-ellipsis">
                          <div class="h-4 bg-gray-300 rounded w-3/4"></div>
                        </td>
                        <td class="px-6 py-4">
                          <div class="h-4 bg-gray-300 rounded w-1/2"></div>
                        </td>
                        <td class="px-6 py-4">
                          <div class="h-4 bg-gray-300 rounded w-1/3"></div>
                        </td>
                        <td class="px-6 py-4">
                          <div class="h-4 bg-gray-300 rounded w-1/3"></div>
                        </td>
                      </tr>
                    {/each}
                  <!-- 實際結果 -->
                  {:else if paginatedData.length > 0 } 
                    {#each paginatedData as row (row.title + row.date)}
                      <tr class="bg-gray-50 hover:bg-gray-200 cursor-pointer" onclick={() => handleRowClick({title: row.title})}>
                        <td class="px-6 py-4 font-medium text-gray-900 overflow-hidden text-ellipsis whitespace-nowrap">{row.title}</td>
                        <td class="px-6 py-4">{row.date}</td>
                        <td class="px-6 py-4">{row.pageviews}</td>
                        <td class="px-6 py-4">{row.zscore}</td>
                      </tr>
                    {/each}
                  {:else}
                    <!-- 無結果 -->
                    <tr class="bg-gray-50">
                      <td class="px-6 py-4 text-center text-gray-500" colspan="4">無結果</td>
                    </tr>
                  {/if}
                </tbody>
              </table>
            </div>
            <!-- 分頁控制 -->
            <div class="flex justify-between items-center mt-4">
              <Button.Root onclick={() => goToPage(currentPage - 1)} disabled={!canGoPrev} 
                class="text-sm px-4 py-2 bg-blue-500 text-white rounded disabled:opacity-50 hover:bg-blue-600 disabled:cursor-not-allowed">
                上一頁
              </Button.Root>
              <span class="text-sm text-gray-600">
                第 {currentPage} 頁 / 共 {totalPages} 頁
              </span>
              <Button.Root onclick={() => goToPage(currentPage + 1)} disabled={!canGoNext} 
                class="text-sm px-4 py-2 bg-blue-500 text-white rounded disabled:opacity-50 hover:bg-blue-600 disabled:cursor-not-allowed">
                下一頁
              </Button.Root>
            </div>
        </div>
      </TabItem>
     </Tabs>   
     {:else}
     <div class="flex items-center justify-center h-full w-full bg-gray-700 text-white text-xs origin-center">
      <PanelLeft class="w-4 h-4 mr-1" />
      <span>搜尋</span>
    </div>
    {/if}
  </div>
  <!-- 左側與中間容器之間的分隔線 -->
  <div
      {@attach drag({
        type:'x', cursor:'ew-resize',
        onDragStart: function(this: Draggable){
          startDragLeftWidth = leftWidth - pxToVw(this.x);
          startDragRelationGraphWidth = relationGraphWidth + pxToVw(this.x);
        },
        onDrag: function(this: Draggable,event: MouseEvent){
            if(!isLeftPanelVisible && this.deltaX<0){
              this.endDrag(event);
              return;
            }
            if(!isRelationGraphPanelVisible && this.deltaX>0){
              this.endDrag(event);
              return;
            }
            leftWidth = startDragLeftWidth + pxToVw(this.x);
            relationGraphWidth = startDragRelationGraphWidth - pxToVw(this.x);
        },
        // bounds: {
        //   minX: 16,
        //   maxX: 6000
        // }
        })} 
      class="cursor-ew-resize bg-gray-500 hover:bg-blue-500 transition-colors z-10 items-center justify-center"
      style:width={DIVIDER_WIDTH_PX}px 
      style:left={initialLeftWidth}vw
      style:position="absolute"
      style:height="100%">
  </div>
  <!-- 關係圖容器 -->
  <div class="h-full grid-cols-start-2 flex flex-col overflow-hidden transition-opacity duration-300"
  style="opacity: {isRelationGraphPanelVisible ? 1 : 0};">
    {#if isRelationGraphPanelVisible}
    <div bind:this={cy_relationContainer} class=" w-full h-full bg-gray-100 rounded-lg"></div>
    {:else}
    <div class="flex items-center justify-center h-full w-full bg-gray-700 text-white text-xs transform rotate-90 origin-center">
      <PanelTop class="w-4 h-4 mr-1" />
      <span>關係圖</span>
    </div>
  {/if}
  </div>
  <!-- 關係圖與子圖之間的分隔線 -->
  <div
      {@attach drag({
        type:'x', cursor:'ew-resize',
        onDragStart: function(this: Draggable){
          startDragRelationGraphWidth = relationGraphWidth - pxToVw(this.x);
          startDragSubgraphWidth = subgraphWidth + pxToVw(this.x);
        },
        onDrag: function(this: Draggable,event: MouseEvent){
          if(!isRelationGraphPanelVisible && this.deltaX<0){
            this.endDrag(event);
            return;
          }
          if(!isSubgraphPanelVisible && this.deltaX>0){
            this.endDrag(event);
            return;
          }
          relationGraphWidth = startDragRelationGraphWidth + pxToVw(this.x);
          subgraphWidth = startDragSubgraphWidth - pxToVw(this.x);
        }
        })} 
      class="cursor-ew-resize bg-gray-500 hover:bg-blue-500 transition-colors z-10 items-center justify-center"
      style:width={DIVIDER_WIDTH_PX}px 
      style:left={initialLeftWidth+initialRelationGraphWidth+pxToVw(DIVIDER_WIDTH_PX)}vw
      style:position="absolute"
      style:height="100%">
  </div>
  <!-- 子圖容器 -->
  <div class="h-full grid-cols-start-2 flex flex-col overflow-hidden transition-opacity duration-300"
    style="opacity: {isSubgraphPanelVisible ? 1 : 0};">
    {#if isSubgraphPanelVisible}
      <div bind:this={cy_subgraphContainer} class=" w-full h-full bg-gray-100 rounded-lg"></div>
    {:else}
      <div class="flex items-center justify-center h-full w-full bg-gray-700 text-white text-xs transform rotate-90 origin-center">
        <PanelRight class="w-4 h-4 mr-1" />
        <span class="hidden md:block">子圖</span>
      </div>
    {/if}
  </div>
  <!-- 子圖與右側容器之間的分隔線 -->
  <div
      {@attach drag({
        type:'x', cursor:'ew-resize',
        onDragStart: function(this: Draggable){
          startDragRightWidth = rightWidth + pxToVw(this.x);
          startDragSubgraphWidth = subgraphWidth - pxToVw(this.x);
        },
        onDrag: function(this: Draggable,event: MouseEvent){
          if(!isSubgraphPanelVisible && this.deltaX<0){
            this.endDrag(event);
            return;
          }
          if(!isRightPanelVisible && this.deltaX>0){
            this.endDrag(event);
            return;
          }
          rightWidth = startDragRightWidth - pxToVw(this.x);
          subgraphWidth = startDragSubgraphWidth + pxToVw(this.x);
        }
        })} 
      class="cursor-ew-resize bg-gray-500 hover:bg-blue-500 transition-colors z-10 items-center justify-center"
      style:width={DIVIDER_WIDTH_PX}px 
      style:left={initialLeftWidth+pxToVw(DIVIDER_WIDTH_PX)+initialRelationGraphWidth+pxToVw(DIVIDER_WIDTH_PX)+initialSubgraphWidth}vw
      style:position="absolute"
      style:height="100%">
  </div>
  <!-- 屬性面板 -->
  <div class="h-full grid-cols-start-3 flex flex-col overflow-hidden transition-opacity duration-300"
  >
  {#if isRightPanelVisible}
    <!-- Tab Bar -->
     <Tabs>
      <TabItem open title="節點">
        <div class="grid grid-rows-2 gap-4 h-[80vh]">
          <div class="grid row-span-1 row-start-1 grid-cols-2">
            <div class="col-span-1">
              <Datepicker bind:value={lastActiveNodeChartStartDate} />
            </div>
            <div class="col-span-1">
              <Datepicker bind:value={lastActiveNodeChartEndDate} />
            </div>
              <div class="col-span-2 h-full w-full" bind:this={lastActiveNodeChartContainer}></div>
          </div>
          
          <div class="row-span-1 row-start-2 border border-gray-200 h-[40vh] flex flex-col">
            <h1 class="text-xl font-bold flex-shrink-0">{lastActiveNodeContent?.title}</h1>
            <div class="overflow-y-auto text-sm text-gray-400 flex-1 min-h-0">
              {lastActiveNodeContent?.introduction}
            </div>
          </div>
        </div>
      </TabItem>
      <TabItem title="社群">
        <div class="grid grid-rows-2 gap-4 h-[80vh]">
          <div class="grid row-span-1 row-start-1 grid-cols-2">
            <div class="col-span-1">
              <Datepicker bind:value={lastActiveCommunityChartStartDate} />
            </div>
            <div class="col-span-1">
              <Datepicker bind:value={lastActiveCommunityChartEndDate} />
            </div>
              <div class="col-span-2 h-full w-full" bind:this={lastActiveCommunityChartContainer}></div>
          </div>
        </div>
      </TabItem>
      <TabItem title="節點群分析">
      </TabItem>
    </Tabs>
  {:else}
    <div class="flex items-center justify-center h-full w-full bg-gray-700 text-white text-xs origin-center">
      <!-- <PanelRight class="w-4 h-4 mr-1" /> -->
      <span>屬性面板</span>
    </div>
  {/if}
  </div>
</div> 
{:else}
<div>Loading...</div>
{/if}