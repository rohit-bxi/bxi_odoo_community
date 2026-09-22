/** @odoo-module */
import { registry } from "@web/core/registry";
import { Component, onMounted, useRef } from "@odoo/owl";
const actionRegistry = registry.category("actions");

class DocumentPreview extends Component {
    /**
     * Setup method
     */
    setup() {
        super.setup(...arguments);
        this.template_div = useRef("document_preview_template_content");
        this.template = this.props.action.params['body_html'];
        this.stamp = this.props.action.params['stamp'];
        onMounted(async () => {
            this.render_template();
        });
    }
    /**
     * Method to render the template
     */
    render_template() {
        if (this.el && this.el.parentElement) {
            this.el.parentElement.classList.add('document_preview_action')
        }
        if (this.template_div.el && this.template) {
            this.template_div.el.innerHTML = this.template;
        }
    }
}
DocumentPreview.template = "DocumentPreviewTemplate";
actionRegistry.add('preview_document', DocumentPreview);
