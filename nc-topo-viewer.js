import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const viewer = document.querySelector("[data-topo-viewer]");

if (viewer) {
  const canvas = viewer.querySelector("[data-topo-canvas]");
  const stage = viewer.querySelector(".topo-viewer__stage");
  const poster = viewer.querySelector("[data-topo-poster]");
  const loading = viewer.querySelector("[data-topo-loading]");
  const slider = viewer.querySelector("[data-topo-slider]");
  const output = viewer.querySelector("[data-topo-output]");
  const status = viewer.querySelector("[data-topo-status]");
  const reset = viewer.querySelector("[data-topo-reset]");
  const profileSelection = document.querySelector("[data-profile-selection]");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(29, 1, 0.01, 100);
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.06;

  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.055;
  controls.autoRotate = !reducedMotion.matches;
  controls.autoRotateSpeed = 0.62;
  controls.enablePan = false;
  controls.minPolarAngle = Math.PI * 0.17;
  controls.maxPolarAngle = Math.PI * 0.77;

  scene.add(new THREE.HemisphereLight(0xeaf7fb, 0x172127, 2.35));
  const keyLight = new THREE.DirectionalLight(0xffffff, 3.1);
  keyLight.position.set(-4, 7, 5);
  scene.add(keyLight);
  const rimLight = new THREE.DirectionalLight(0x7ec8df, 1.4);
  rimLight.position.set(5, 2, -4);
  scene.add(rimLight);

  let manifest;
  let model;
  let layers = [];
  let initialView;
  let selectedOutline;

  function resize() {
    const width = Math.max(stage.clientWidth, 1);
    const height = Math.max(stage.clientHeight, 1);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  function materialList(material) {
    return Array.isArray(material) ? material : [material];
  }

  function prepareMaterials(root) {
    root.traverse((object) => {
      if (!object.isMesh) return;
      object.frustumCulled = false;
      object.material = Array.isArray(object.material)
        ? object.material.map((material) => material.clone())
        : object.material.clone();

      materialList(object.material).forEach((material) => {
        material.userData.baseColor = material.color?.clone();
        material.userData.baseEmissive = material.emissive?.clone();
        material.userData.baseEmissiveIntensity = material.emissiveIntensity ?? 1;
        material.side = THREE.DoubleSide;
        material.roughness = Math.max(material.roughness ?? 0.72, 0.68);
      });
    });
  }

  function setLayerEmphasis(layer, selected) {
    layer.node.traverse((object) => {
      if (!object.isMesh) return;
      materialList(object.material).forEach((material) => {
        if (material.userData.baseColor && material.color) {
          material.color.copy(material.userData.baseColor);
        }
        if (material.emissive) {
          material.emissive.copy(material.userData.baseEmissive || new THREE.Color(0x000000));
          material.emissiveIntensity = material.userData.baseEmissiveIntensity ?? 1;
          if (selected) {
            material.emissive.lerp(new THREE.Color(0xf4e7cf), 0.7);
            material.emissiveIntensity = 0.25;
          }
        }
        material.needsUpdate = true;
      });
    });
  }

  function removeOutline() {
    if (!selectedOutline) return;
    selectedOutline.parent?.remove(selectedOutline);
    selectedOutline.traverse((object) => {
      object.geometry?.dispose();
      object.material?.dispose();
    });
    selectedOutline = undefined;
  }

  function addOutline(layer) {
    removeOutline();
    selectedOutline = new THREE.Group();
    selectedOutline.name = "selected-sheet-outline";
    layer.node.traverse((object) => {
      if (!object.isMesh) return;
      const edges = new THREE.EdgesGeometry(object.geometry, 32);
      const line = new THREE.LineSegments(
        edges,
        new THREE.LineBasicMaterial({ color: 0xf8f2e7, transparent: true, opacity: 0.88 })
      );
      line.matrixAutoUpdate = false;
      line.matrix.copy(object.matrixWorld);
      selectedOutline.add(line);
    });
    scene.add(selectedOutline);
  }

  function formatElevation(layer) {
    if (!layer || Number(layer.elevation) === 0) return "Base";
    return `${Number(layer.elevation).toLocaleString("en-US")} ft`;
  }

  function updateProfile(index) {
    if (!profileSelection || !manifest?.profile) return;
    const profile = manifest.profile;
    const viewBoxHeight = Number(profile.viewBoxHeight || profile.viewBox?.[3] || 840);
    const viewBoxWidth = Number(profile.viewBoxWidth || profile.viewBox?.[2] || 1600);
    const bottom = Number(profile.bottom || 735);
    const bandHeight = Number(profile.bandHeight || 5);
    const y = bottom - (index + 0.5) * bandHeight;
    if (Number.isFinite(Number(profile.left))) {
      profileSelection.style.left = `${(Number(profile.left) / viewBoxWidth) * 100}%`;
    }
    if (Number.isFinite(Number(profile.right))) {
      profileSelection.style.right = `${100 - (Number(profile.right) / viewBoxWidth) * 100}%`;
    }
    profileSelection.style.top = `${(y / viewBoxHeight) * 100}%`;
    profileSelection.style.opacity = "1";
  }

  function showThrough(index) {
    const bounded = Math.max(0, Math.min(index, layers.length - 1));
    layers.forEach((layer, layerIndex) => {
      layer.node.visible = layerIndex <= bounded;
      setLayerEmphasis(layer, layerIndex === bounded);
    });

    const selected = layers[bounded];
    addOutline(selected);
    const elevation = formatElevation(selected);
    output.textContent = `${bounded + 1} of ${layers.length} · ${elevation === "Base" ? "base" : `through ${elevation}`}`;
    status.textContent = bounded === layers.length - 1
      ? "Showing the full stack."
      : `Showing the ${elevation.toLowerCase()} sheet and every sheet below it.`;
    slider.value = String(bounded);
    slider.setAttribute("aria-valuetext", elevation);
    updateProfile(bounded);
  }

  function findLayerNode(entry) {
    const named = entry.nodeName ? model.getObjectByName(entry.nodeName) : undefined;
    if (named) return named;
    let match;
    model.traverse((object) => {
      if (match) return;
      if (Number(object.userData?.layerIndex) === Number(entry.index)) match = object;
    });
    return match;
  }

  function collectLayers() {
    if (Array.isArray(manifest?.layers)) {
      layers = manifest.layers
        .map((entry) => ({ ...entry, node: findLayerNode(entry) }))
        .filter((entry) => entry.node)
        .sort((a, b) => Number(a.index) - Number(b.index));
    }

    if (layers.length) return;

    model.traverse((object) => {
      const index = Number(object.userData?.layerIndex);
      if (Number.isInteger(index)) {
        layers.push({
          index,
          elevation: Number(object.userData?.elevation || 0),
          label: object.userData?.label,
          node: object,
        });
      }
    });
    layers.sort((a, b) => a.index - b.index);
  }

  function frameModel() {
    model.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(model);
    const center = box.getCenter(new THREE.Vector3());
    model.position.sub(center);
    model.updateMatrixWorld(true);

    const recenteredBox = new THREE.Box3().setFromObject(model);
    const sphere = recenteredBox.getBoundingSphere(new THREE.Sphere());
    const radius = Math.max(sphere.radius, 0.5);
    const direction = new THREE.Vector3(0.88, 0.63, 1.16).normalize();
    const distance = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov * 0.5)) * 1.02;
    camera.near = Math.max(distance / 400, 0.01);
    camera.far = distance * 12;
    camera.position.copy(direction.multiplyScalar(distance));
    camera.updateProjectionMatrix();
    controls.target.set(0, 0, 0);
    controls.minDistance = distance * 0.45;
    controls.maxDistance = distance * 2.2;
    controls.update();
    initialView = {
      position: camera.position.clone(),
      target: controls.target.clone(),
    };
  }

  function resetView() {
    if (!initialView) return;
    camera.position.copy(initialView.position);
    controls.target.copy(initialView.target);
    controls.update();
  }

  function fail(error) {
    console.error("North Carolina topo viewer failed to load:", error);
    loading.textContent = "The interactive model could not load. The QGIS image is shown instead.";
    loading.classList.add("topo-viewer__loading--error");
    slider.disabled = true;
    reset.disabled = true;
  }

  async function loadViewer() {
    try {
      const [manifestResponse, gltf] = await Promise.all([
        fetch("assets/models/nc-topo-layered.json"),
        new GLTFLoader().loadAsync("assets/models/nc-topo-layered.glb"),
      ]);
      if (!manifestResponse.ok) throw new Error(`Manifest returned ${manifestResponse.status}`);
      manifest = await manifestResponse.json();
      model = gltf.scene;
      prepareMaterials(model);
      scene.add(model);
      collectLayers();
      if (!layers.length) throw new Error("No named contour sheets were found in the model.");

      slider.max = String(layers.length - 1);
      slider.value = String(layers.length - 1);
      slider.disabled = false;
      reset.disabled = false;
      frameModel();
      showThrough(layers.length - 1);
      resize();
      poster.hidden = true;
      loading.hidden = true;
      viewer.classList.add("topo-viewer--ready");
    } catch (error) {
      fail(error);
    }
  }

  slider.addEventListener("input", () => showThrough(Number(slider.value)));
  reset.addEventListener("click", resetView);
  reducedMotion.addEventListener?.("change", (event) => {
    controls.autoRotate = !event.matches;
  });

  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(stage);
  resize();

  function render() {
    controls.update();
    renderer.render(scene, camera);
    requestAnimationFrame(render);
  }

  render();
  loadViewer();
}
