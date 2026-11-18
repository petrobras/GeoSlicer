def populate_widgets(cls):
    """Initialize dictionary with module's interface widgets reference."""
    input_selector = cls.find_widget("Input Selector")
    pores_selector = cls.find_widget("Pores Selector")
    apply_button = cls.find_widget("Apply Button")
    cancel_button = cls.find_widget("Cancel Button")
    output_prefix = cls.find_widget("Output Prefix")
    pore_table_selector = cls.find_widget("Pore Table Selector")
    generate_visualization_button = cls.find_widget("Generate Visualization Button")
    generate_visualization_checkbox = cls.find_widget("Generate Visualization Checkbox")

    # Assert widget existance
    cls.assertIsNotNone(input_selector)
    cls.assertIsNotNone(pores_selector)
    cls.assertIsNotNone(apply_button)
    cls.assertIsNotNone(cancel_button)
    cls.assertIsNotNone(pore_table_selector)
    cls.assertIsNotNone(generate_visualization_button)
    cls.assertIsNotNone(generate_visualization_checkbox)

    cls._widgets["Input Selector"] = input_selector
    cls._widgets["Pores Selector"] = pores_selector
    cls._widgets["Apply Button"] = apply_button
    cls._widgets["Cancel Button"] = cancel_button
    cls._widgets["Output Prefix"] = output_prefix
    cls._widgets["Pore Table Selector"] = pore_table_selector
    cls._widgets["Generate Visualization Button"] = generate_visualization_button
    cls._widgets["Generate Visualization Checkbox"] = generate_visualization_checkbox
