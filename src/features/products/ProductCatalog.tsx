import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  AlertCircle,
  Archive,
  ArrowDownWideNarrow,
  ArrowUpWideNarrow,
  Check,
  ChevronDown,
  Edit3,
  LoaderCircle,
  Package,
  Plus,
  Search,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import {
  createProduct,
  deleteProduct,
  generateProductDescription,
  getAIModelStatus,
  listProducts,
  updateProduct,
} from "@/lib/api";
import type {
  AIModelStatus,
  Product,
  ProductAvailability,
  ProductInput,
  ProductSort,
} from "@/lib/types";

type AvailabilityFilter = ProductAvailability | "";
type EditorState = { product: Product | null } | null;

const EMPTY_PRODUCT: ProductInput = {
  name: "",
  description: "",
  price: "0",
  currency: "USD",
  stock_quantity: 0,
  category: "",
  brand: "",
  specifications: {},
  availability: "available",
};

export function ProductCatalog() {
  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [modelStatus, setModelStatus] = useState<AIModelStatus | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [availability, setAvailability] = useState<AvailabilityFilter>("");
  const [sort, setSort] = useState<ProductSort>("name");
  const [descending, setDescending] = useState(false);
  const [editor, setEditor] = useState<EditorState>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const loadSequence = useRef(0);

  const loadProducts = useCallback(async () => {
    const sequence = ++loadSequence.current;
    try {
      const result = await listProducts({ query, category, availability, sort, descending });
      if (sequence !== loadSequence.current) return;
      setProducts(result.products);
      setCategories(result.categories);
      setError(null);
    } catch (reason) {
      if (sequence === loadSequence.current) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      if (sequence === loadSequence.current) setIsLoading(false);
    }
  }, [availability, category, descending, query, sort]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadProducts(), query ? 180 : 0);
    return () => window.clearTimeout(timer);
  }, [loadProducts, query]);

  useEffect(() => {
    let active = true;
    void getAIModelStatus()
      .then((status) => {
        if (active) setModelStatus(status);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      active = false;
    };
  }, []);

  async function saveProduct(input: ProductInput) {
    setBusy(true);
    try {
      if (editor?.product) await updateProduct(editor.product.id, input);
      else await createProduct(input);
      setEditor(null);
      await loadProducts();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function removeProduct(product: Product) {
    if (!window.confirm(`Delete “${product.name}” from the catalog?`)) return;
    setBusy(true);
    try {
      await deleteProduct(product.id);
      await loadProducts();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="product-workspace">
      <header className="product-page-header">
        <div>
          <h1>Products</h1>
        </div>
        <button className="product-primary-button" onClick={() => setEditor({ product: null })} type="button">
          <Plus size={15} />Add product
        </button>
      </header>

      <section aria-label="Catalog overview" className="catalog-overview">
        <div><strong>{products.length}</strong><span>Catalog products</span></div>
        <div className="catalog-overview-divider" />
        <div><strong>{categories.length}</strong><span>Categories</span></div>
      </section>

      {error && (
        <div className="product-alert" role="alert">
          <AlertCircle size={14} /><span>{error}</span>
          <button aria-label="Dismiss error" onClick={() => setError(null)} type="button"><X size={13} /></button>
        </div>
      )}

      <div className="product-toolbar">
        <label className="product-search">
          <Search aria-hidden="true" size={14} />
          <input
            aria-label="Search products"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search name, brand, category…"
            value={query}
          />
          {query && <button aria-label="Clear search" onClick={() => setQuery("")} type="button"><X size={13} /></button>}
        </label>
        <label className="product-filter">
          <span>Category</span>
          <span className="product-select-wrap">
            <select aria-label="Filter by category" onChange={(event) => setCategory(event.target.value)} value={category}>
              <option value="">All categories</option>
              {categories.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
            <ChevronDown aria-hidden="true" size={12} />
          </span>
        </label>
        <label className="product-filter">
          <span>Status</span>
          <span className="product-select-wrap">
            <select
              aria-label="Filter by availability"
              onChange={(event) => setAvailability(event.target.value as AvailabilityFilter)}
              value={availability}
            >
              <option value="">All statuses</option>
              <option value="available">In stock</option>
              <option value="out_of_stock">Out of stock</option>
              <option value="discontinued">Discontinued</option>
            </select>
            <ChevronDown aria-hidden="true" size={12} />
          </span>
        </label>
        <label className="product-filter sort-filter">
          <span>Sort by</span>
          <span className="product-select-wrap">
            <select aria-label="Sort products" onChange={(event) => setSort(event.target.value as ProductSort)} value={sort}>
              <option value="name">Name</option>
              <option value="price">Price</option>
              <option value="stock">Stock</option>
            </select>
            <ChevronDown aria-hidden="true" size={12} />
          </span>
        </label>
        <button
          aria-label={descending ? "Sort ascending" : "Sort descending"}
          className="product-sort-direction"
          onClick={() => setDescending((value) => !value)}
          title={descending ? "Descending" : "Ascending"}
          type="button"
        >
          {descending ? <ArrowDownWideNarrow size={15} /> : <ArrowUpWideNarrow size={15} />}
        </button>
      </div>

      <div className="product-table-wrap">
        <table className="product-table">
          <thead><tr>
            <th>Product</th><th>Category</th><th>Price</th><th>Stock</th><th>Availability</th><th><span className="sr-only">Actions</span></th>
          </tr></thead>
          <tbody>
            {products.map((product) => (
              <tr key={product.id}>
                <td>
                  <button className="product-name-cell" onClick={() => setEditor({ product })} type="button">
                    <span className="product-row-icon"><Package size={15} /></span>
                    <span>
                      <strong>{product.name}</strong>
                      {(product.brand || product.description) && <small>{product.brand || product.description}</small>}
                    </span>
                  </button>
                </td>
                <td><span className="product-category">{product.category}</span></td>
                <td className="product-price">{formatPrice(product.price, product.currency)}</td>
                <td className="product-stock">{product.stock_quantity} <span>units</span></td>
                <td><AvailabilityBadge availability={product.availability} /></td>
                <td>
                  <div className="product-row-actions">
                    <button aria-label={`Edit ${product.name}`} onClick={() => setEditor({ product })} type="button"><Edit3 size={14} /></button>
                    <button aria-label={`Delete ${product.name}`} disabled={busy} onClick={() => void removeProduct(product)} type="button"><Trash2 size={14} /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!isLoading && products.length === 0 && (
          <div className="catalog-empty">
            <div className="catalog-empty-icon">{query || category || availability ? <Search size={19} /> : <Archive size={19} />}</div>
            {query || category || availability ? (
              <>
                <h2>No matching products</h2>
                <p>Try changing the search or filters.</p>
              </>
            ) : <h2>No products</h2>}
          </div>
        )}
        {isLoading && <div className="catalog-loading"><span className="mini-spinner" />Loading local catalog…</div>}
      </div>

      {editor && (
        <ProductEditor
          busy={busy}
          modelStatus={modelStatus}
          onModelStatusChange={setModelStatus}
          onClose={() => setEditor(null)}
          onSave={saveProduct}
          product={editor.product}
        />
      )}
    </section>
  );
}

function ProductEditor({
  product,
  busy,
  modelStatus,
  onModelStatusChange,
  onClose,
  onSave,
}: {
  product: Product | null;
  busy: boolean;
  modelStatus: AIModelStatus | null;
  onModelStatusChange: (status: AIModelStatus) => void;
  onClose: () => void;
  onSave: (input: ProductInput) => Promise<void>;
}) {
  const [form, setForm] = useState<ProductInput>(() =>
    product ? {
      name: product.name,
      description: product.description,
      price: product.price,
      currency: product.currency,
      stock_quantity: product.stock_quantity,
      category: product.category,
      brand: product.brand,
      specifications: product.specifications,
      availability: product.availability === "discontinued" ? "discontinued" : "available",
    } : EMPTY_PRODUCT,
  );
  const [specificationsText, setSpecificationsText] = useState(
    Object.entries(product?.specifications ?? {}).map(([key, value]) => `${key}: ${String(value ?? "")}`).join("\n"),
  );
  const [formError, setFormError] = useState<string | null>(null);
  const [descriptionWasGenerated, setDescriptionWasGenerated] = useState(false);
  const [generatingDescription, setGeneratingDescription] = useState(false);

  useEffect(() => {
    if (!generatingDescription) return;
    const timer = window.setInterval(() => {
      void getAIModelStatus()
        .then(onModelStatusChange)
        .catch((reason: unknown) => {
          setFormError(reason instanceof Error ? reason.message : String(reason));
        });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [generatingDescription, onModelStatusChange]);

  function setField<K extends keyof ProductInput>(key: K, value: ProductInput[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function draftDescription() {
    if (!form.name.trim() || !form.category.trim()) {
      setFormError("Add a product name and category before drafting a description.");
      return;
    }
    const specifications = parseSpecifications(specificationsText);
    if (!specifications) {
      setFormError("Enter each specification as “Name: value” before drafting.");
      return;
    }
    setGeneratingDescription(true);
    setFormError(null);
    try {
      const draft = await generateProductDescription({
        name: form.name.trim(),
        price: form.price,
        currency: form.currency.toUpperCase(),
        category: form.category.trim(),
        brand: form.brand?.trim() || null,
        specifications,
      });
      setField("description", draft.description);
      setDescriptionWasGenerated(draft.requires_review);
      onModelStatusChange(await getAIModelStatus());
    } catch (reason) {
      setFormError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setGeneratingDescription(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const specifications = parseSpecifications(specificationsText);
    if (!specifications) {
      setFormError("Enter each specification as “Name: value”.");
      return;
    }
    setFormError(null);
    await onSave({
      ...form,
      specifications,
      name: form.name.trim(),
      category: form.category.trim(),
      brand: form.brand?.trim() || null,
      description: form.description?.trim() || null,
      currency: form.currency.trim().toUpperCase(),
    });
  }

  return (
    <div className="product-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section aria-labelledby="product-editor-title" aria-modal="true" className="product-dialog" role="dialog">
        <header className="product-dialog-header">
          <div><h2 id="product-editor-title">{product ? "Edit product" : "Add product"}</h2></div>
          <button aria-label="Close product editor" className="product-dialog-close" onClick={onClose} type="button"><X size={16} /></button>
        </header>
        <form onSubmit={(event) => void submit(event)}>
          <div className="product-form-grid">
            <label className="product-form-field full"><span>Product name <b>*</b></span>
              <input autoFocus maxLength={160} onChange={(event) => setField("name", event.target.value)} required value={form.name} />
            </label>
            <label className="product-form-field"><span>Price <b>*</b></span>
              <input min="0" onChange={(event) => setField("price", event.target.value)} required step="0.01" type="number" value={form.price} />
            </label>
            <label className="product-form-field"><span>Currency</span>
              <input maxLength={3} onChange={(event) => setField("currency", event.target.value.toUpperCase())} required value={form.currency} />
            </label>
            <label className="product-form-field"><span>Stock quantity <b>*</b></span>
              <input min="0" onChange={(event) => setField("stock_quantity", Number(event.target.value))} required step="1" type="number" value={form.stock_quantity} />
            </label>
            <label className="product-form-field"><span>Category <b>*</b></span>
              <input maxLength={100} onChange={(event) => setField("category", event.target.value)} required value={form.category} />
            </label>
            <label className="product-form-field"><span>Brand</span>
              <input maxLength={100} onChange={(event) => setField("brand", event.target.value)} value={form.brand ?? ""} />
            </label>
            <label className="product-form-field"><span>Listing status</span>
              <span className="product-select-wrap">
                <select onChange={(event) => setField("availability", event.target.value as ProductInput["availability"])} value={form.availability}>
                  <option value="available">Active</option><option value="discontinued">Discontinued</option>
                </select><ChevronDown aria-hidden="true" size={12} />
              </span>
            </label>
            <div className="product-form-field full">
              <div className="product-description-heading">
                <label htmlFor="product-description">Description</label>
                <button
                  className="product-draft-button"
                  disabled={generatingDescription || !form.name.trim() || !form.category.trim()}
                  onClick={() => void draftDescription()}
                  type="button"
                >
                  {generatingDescription ? <LoaderCircle className="spin" size={12} /> : <Sparkles size={12} />}
                  {generatingDescription ? "Drafting locally…" : "Draft with local AI"}
                </button>
              </div>
              <textarea
                id="product-description"
                maxLength={5000}
                onChange={(event) => setField("description", event.target.value)}
                rows={3}
                value={form.description ?? ""}
              />
              <small>
                {generatingDescription && modelStatus?.status === "loading"
                  ? "Preparing the local model. First-time setup may download about 1.1 GB."
                  : descriptionWasGenerated
                  ? "AI draft: review and edit before saving. Only the provided catalog details were supplied."
                  : !modelStatus?.downloaded && !modelStatus?.loaded
                    ? "Optional local Qwen model. The first AI draft downloads about 1.1 GB; review the suggestion before saving."
                    : "Description is optional. AI drafts are never saved without your review."}
              </small>
            </div>
            <label className="product-form-field full"><span>Specifications <small>Optional · one per line</small></span>
              <textarea onChange={(event) => setSpecificationsText(event.target.value)} placeholder={"Color: Midnight\nCapacity: 256 GB"} rows={3} value={specificationsText} />
            </label>
          </div>
          {formError && <p className="product-form-error" role="alert"><AlertCircle size={13} />{formError}</p>}
          <footer className="product-dialog-actions">
            <button className="product-secondary-button" onClick={onClose} type="button">Cancel</button>
            <button className="product-primary-button" disabled={busy} type="submit">
              {busy ? <span className="mini-spinner" /> : <Check size={14} />}{product ? "Save changes" : "Save product"}
            </button>
          </footer>
        </form>
      </section>
    </div>
  );
}

function parseSpecifications(text: string): Record<string, string> | null {
  const specifications: Record<string, string> = {};
  for (const line of text.split("\n").filter((item) => item.trim())) {
    const separator = line.indexOf(":");
    if (separator <= 0) return null;
    const key = line.slice(0, separator).trim();
    const value = line.slice(separator + 1).trim();
    if (!key || !value) return null;
    specifications[key] = value;
  }
  return specifications;
}

function AvailabilityBadge({ availability }: { availability: ProductAvailability }) {
  const labels: Record<ProductAvailability, string> = {
    available: "In stock",
    out_of_stock: "Out of stock",
    discontinued: "Discontinued",
  };
  return <span className={`availability-badge ${availability}`}><span />{labels[availability]}</span>;
}

function formatPrice(price: string, currency: string): string {
  const amount = Number(price);
  if (!Number.isFinite(amount)) return `${price} ${currency}`;
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(amount);
  } catch {
    return `${amount.toFixed(2)} ${currency}`;
  }
}
