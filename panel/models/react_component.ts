import type * as p from "@bokehjs/core/properties"
import type {Transform} from "sucrase"

import {
  ReactiveESM, ReactiveESMView, model_getter, model_setter,
} from "./reactive_esm"

export class ReactComponentView extends ReactiveESMView {
  declare model: ReactComponent
  declare style_cache: HTMLHeadElement
  model_getter = model_getter
  model_setter = model_setter
  react_root: any

  _force_update_callbacks: (() => void)[] = []

  override render_esm(): void {
    if (this.model.compiled === null || this.model.render_module === null) {
      return
    }
    if (this.model.usesMui) {
      if (this.model.root_node) {
        this.style_cache = document.head
      } else {
        this.style_cache = document.createElement("head")
        this.shadow_el.insertBefore(this.style_cache, this.container)
      }
    }
    this.accessed_properties = []
    for (const lf of this._lifecycle_handlers.keys()) {
      (this._lifecycle_handlers.get(lf) || []).splice(0)
    }
    this.model.disconnect_watchers(this)
    this.model.render_module.then((mod: any) => {
      this.react_root = mod.default.render(this.model.id)
    })
  }

  on_force_update(cb: () => void): void {
    this._force_update_callbacks.push(cb)
  }

  force_update(): void {
    for (const cb of this._force_update_callbacks) {
      cb()
    }
  }

  override remove(): void {
    super.remove()
    this._force_update_callbacks = []
    if (this.react_root) {
      this.react_root.then((root: any) => root.unmount())
    }
  }

  override render(): void {
    if (this.react_root) {
      this.react_root.then((root: any) => root.unmount())
    }
    this._force_update_callbacks = []
    super.render()
  }

  override after_rendered(): void {
    const handlers = (this._lifecycle_handlers.get("after_render") || [])
    for (const cb of handlers) {
      cb()
    }
    if (!this._rendered) {
      for (const cb of (this._lifecycle_handlers.get("after_layout") || [])) {
        cb()
      }
    }
    this._rendered = true
  }
}

export namespace ReactComponent {
  export type Attrs = p.AttrsOf<Props>

  export type Props = ReactiveESM.Props & {
    root_node: p.Property<string | null>
  }
}

export interface ReactComponent extends ReactComponent.Attrs {}

export class ReactComponent extends ReactiveESM {
  declare properties: ReactComponent.Props
  override sucrase_transforms: Transform[] = ["typescript", "jsx"]

  constructor(attrs?: Partial<ReactComponent.Attrs>) {
    super(attrs)
  }

  get usesMui(): boolean {
    if (this.importmap?.imports) {
      return Object.keys(this.importmap?.imports).some(k => k.startsWith("@mui"))
    }
    return false
  }

  protected override _render_code(): string {
    let [import_code, bundle_code] = ["", ""]
    const cache_key = (this.bundle === "url") ? this.esm : (this.bundle || `${this.class_name}-${this.esm.length}`)
    if (this.bundle) {
      bundle_code = `
  const ns = await view._module_cache.get("${cache_key}")
  const {React, createRoot} = ns.default`
    } else {
      import_code = `
import * as React from "react"
import { createRoot } from "react-dom/client"`
    }
    let init_code = ""
    let render_code = ""
    if (this.usesMui) {
      if (this.bundle) {
        bundle_code = `
  const ns = await view._module_cache.get("${cache_key}")
  const {CacheProvider, React, createCache, createRoot} = ns.default`
      } else {
        import_code = `
${import_code}
import createCache from "@emotion/cache"
import { CacheProvider } from "@emotion/react"`
      }
      init_code = `
  const css_key = id.replace("-", "").replace(/\d/g, (digit) => String.fromCharCode(digit.charCodeAt(0) + 49)).toLowerCase()
  this.mui_cache = createCache({
    key: 'css-'+css_key,
    prepend: true,
    container: view.style_cache,
  })`
      render_code = `
  if (rendered) {
    rendered = React.createElement(CacheProvider, {value: this.mui_cache}, rendered)
  }`
    }
    return `
${import_code}

async function render(id) {
  const view = Bokeh.index.find_one_by_id(id)
  if (view == null) {
    return null
  }

  ${bundle_code}

  class Child extends React.PureComponent {

    constructor(props) {
      super(props)
      this.render_callback = null
    }

    get view() {
      const child = this.props.parent.model.data[this.props.name]
      const model = this.props.index == null ? child : child[this.props.index]
      return this.props.parent.get_child_view(model)
    }

    get element() {
      const view = this.view
      return view == null ? null : view.el
    }

    componentDidMount() {
      const view = this.view
      if (view == null) { return }
      this.props.parent.rerender_(view)
      this.render_callback = (new_views) => {
        const view = this.view
        if (!view) {
          return
        } else if (new_views.includes(view)) {
          if (this.props.id === undefined) { this.forceUpdate() }
          this.props.parent.rerender_(view)
        } else {
          this.forceUpdate()
          if (view.force_update) { view.force_update() }
        }
      }
      this.props.parent.on_child_render(this.props.name, this.render_callback)
      this.props.parent.notify_mount(this.props.name, view.model.id)
    }

    componentWillUnmount() {
      if (this.render_callback) {
        this.props.parent.remove_on_child_render(this.props.name, this.render_callback)
      }
    }

    render() {
      return React.createElement('div', {
        className: "child-wrapper",
        ref: (ref) => {
          if (ref != null && this.view != null) {
            ref.appendChild(this.element)
          }
        }
      })
    }
  }

  function react_getter(target, name) {
    if (name === "useMount") {
      return (callback) => React.useEffect(() => {
        target.model_proxy.on('lifecycle:mounted', callback)
        return () => target.model_proxy.off('lifecycle:mounted', callback)
      }, [])
    } if (name == "useState") {
      return (prop) => {
        const data_model = target.model.data
        const propPath = prop.split(".")
        let targetModel = data_model
        let resolvedProp = null

        for (let i = 0; i < propPath.length - 1; i++) {
          if (targetModel && targetModel.properties && propPath[i] in targetModel.properties) {
            targetModel = targetModel[propPath[i]]
          } else {
            // Stop if any part of the path is missing
            targetModel = null
            break
          }
        }
        if (targetModel && targetModel.attributes && propPath[propPath.length - 1] in targetModel.attributes) {
          resolvedProp = propPath[propPath.length - 1]
        }
        if (resolvedProp && targetModel) {
          const [value, setValue] = React.useState(targetModel.attributes[resolvedProp])

          react_proxy.on(prop, () => setValue(targetModel.attributes[resolvedProp]))

          React.useEffect(() => {
              targetModel.setv({ [resolvedProp]: value })
          }, [value])

          return [value, setValue]
        }
        throw ReferenceError("Could not resolve " + prop + " on " + target.model.class_name)
      }
    } else if (name === "get_child") {
      return (child) => {
        const data_model = target.model.data
        const value = data_model.attributes[child]
        if (Array.isArray(value)) {
          const [children_state, set_children] = React.useState(value.map((model, i) =>
            React.createElement(Child, { parent: target, name: child, key: child+i, index: i })
          ))
          React.useEffect(() => {
            target.on_child_render(child, () => {
              const current_models = data_model.attributes[child]
              const previous_models = children_state.map(child => child.props.index)
              if (current_models.length !== previous_models.length ||
                  current_models.some((model, i) => i !== previous_models[i])) {
                set_children(current_models.map((model, i) => (
                  React.createElement(Child, { parent: target, name: child, key: child+i, index: i })
                )))
              }
            })
          }, [])
          return children_state
        } else {
          return React.createElement(Child, {parent: target, name: child})
        }
      }
    }
    return target.model_getter(target, name)
  }

  const react_proxy = new Proxy(view, {
    get: react_getter,
    set: view.model_setter
  })

  class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    // initialize the error state
    this.state = { hasError: false }
  }

  // if an error happened, set the state to true
  static getDerivedStateFromError(error) {
    return { hasError: true }
  }

  componentDidCatch(error) {
    this.props.view.render_error(error)
  }

  render() {
    if (this.state.hasError) {
      return React.createElement('div')
    }
    return React.createElement('div', {className: "error-wrapper"}, this.props.children)
  }
  }

  class Component extends React.Component {

    constructor(props) {
      super(props)
      ${init_code}
    }

    componentDidMount() {
      this.props.view.on_force_update(() => {
        ${init_code}
        this.forceUpdate()
      })
      this.props.view._changing = false
      this.props.view.after_rendered()
    }

    render() {
      let rendered = React.createElement(this.props.view.render_fn, this.props)
      if (this.props.view.model.dev) {
        rendered = React.createElement(ErrorBoundary, {view}, rendered)
      }
      ${render_code}
      return rendered
    }
  }

  const props = {view, model: react_proxy, data: view.model.data, el: view.container}
  const rendered = React.createElement(Component, props)
  if (rendered) {
    view._changing = true
    let container
    if (view.model.root_node) {
      container = document.querySelector(view.model.root_node)
      if (container == null) {
        container = document.createElement("div")
        container.id = view.model.root_node.replace("#", "")
        document.body.append(container)
      }
    } else {
      container = view.container
    }
    const root = createRoot(container)
    try {
      root.render(rendered)
    } catch(e) {
      view.render_error(e)
    }
    return root
  }
}

export default {render}`
  }

  override compile(): string | null {
    const compiled = super.compile()
    if (this.bundle) {
      return compiled
    } else if (compiled === null || !compiled.includes("React")) {
      return compiled
    }
    return `
import * as React from "react"

${compiled}`
  }

  protected override get _render_cache_key() {
    const cache_key = (this.bundle === "url") ? this.esm : (this.bundle || `${this.class_name}-${this.esm.length}`)
    return `react-${this.usesMui}-${cache_key}`
  }

  static override __module__ = "panel.models.esm"

  static {
    this.prototype.default_view = ReactComponentView
    this.define<ReactComponent.Props>(({Nullable, Str}) => ({
      root_node:  [ Nullable(Str),     null ],
    }))
  }
}
