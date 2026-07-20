/** @type {import("@eodash/eodash").Template} */
export default {
  gap: 16,
  background: {
    id: "background-map",
    type: "internal",
    widget: {
      name: "EodashMap",
      properties: {
        enableCompare: false,
        zoomToExtent: true,
      },
    },
  },
  widgets: [
    {
      id: Symbol(),
      type: "web-component",
      title: "Plant trait controls",
      layout: { x: 0, y: 1, w: 3, h: 8 },
      widget: {
        tagName: "plant-trait-controls",
        link: async () => ({}),
      },
    },
    {
      defineWidget: (selectedSTAC) => {
        return selectedSTAC
          ? {
              id: "Information",
              title: "Information",
              layout: { x: 9, y: 0, w: 3, h: 6 },
              type: "internal",
              widget: {
                name: "EodashStacInfo",
                properties: {
                  showIndicatorsBtn: false,
                  showLayoutSwitcher: false,
                },
              },
            }
          : null;
      },
    },
    {
      defineWidget: (selectedSTAC) => {
        return selectedSTAC
          ? {
              id: "Datepicker",
              type: "internal",
              layout: { x: 5, y: 8, w: 2, h: 4 },
              title: "Date",
              widget: {
                name: "EodashDatePicker",
                properties: {
                  hintText: `<b>Hint:</b> closest available date is displayed <br />
                                on map (see Analysis Layers)`,
                  toggleCalendar: true,
                },
              },
            }
          : null;
      },
    },
  ],
};
