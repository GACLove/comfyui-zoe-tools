import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

app.registerExtension({
    name: "zoenode.RouterPromptEnhance.Models",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "RouterPromptEnhance") return;
        const previous = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            previous?.apply(this, arguments);
            this.addWidget("button", "选择 / 刷新模型", null, async () => {
                const baseUrl = this.widgets?.find((w) => w.name === "base_url")?.value || "";
                const modelWidget = this.widgets?.find((w) => w.name === "model");
                if (!modelWidget) return;
                try {
                    const response = await api.fetchApi("/zoe/router-pe/models", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ base_url: baseUrl }),
                    });
                    const payload = await response.json();
                    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
                    const dialog = document.createElement("dialog");
                    const form = document.createElement("form");
                    form.method = "dialog";
                    const label = document.createElement("label");
                    label.textContent = "选择 PE 模型： ";
                    const select = document.createElement("select");
                    for (const id of payload.models) {
                        const option = document.createElement("option");
                        option.value = id;
                        option.textContent = id;
                        select.append(option);
                    }
                    if (payload.models.includes(modelWidget.value)) select.value = modelWidget.value;
                    label.append(select);
                    const confirm = document.createElement("button");
                    confirm.type = "submit";
                    confirm.value = "select";
                    confirm.textContent = "选择";
                    const cancel = document.createElement("button");
                    cancel.type = "submit";
                    cancel.value = "cancel";
                    cancel.textContent = "取消";
                    form.append(label, confirm, cancel);
                    dialog.append(form);
                    document.body.append(dialog);
                    dialog.addEventListener("close", () => {
                        if (dialog.returnValue === "select") {
                            modelWidget.value = select.value;
                            modelWidget.callback?.(select.value);
                            app.graph.setDirtyCanvas(true, true);
                        }
                        dialog.remove();
                    }, { once: true });
                    dialog.showModal();
                } catch (error) {
                    alert(`获取 PE 模型失败：${error.message}`);
                }
            }, { serialize: false });
        };
    },
});
