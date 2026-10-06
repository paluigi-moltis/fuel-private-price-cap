import polars as pl

disp = pl.read_csv("output/tables/province_dispersion.csv")
wide = disp.pivot(index=["provincia_istat", "fuel"], on="phase", values="sd")
print("cells:", wide.height)
print("sd_post > sd_pre:", (wide["sd_post"] > wide["sd_pre"]).sum())
for f in ["Benzina", "Gasolio"]:
    sub = wide.filter(pl.col("fuel") == f)
    print(f, "mean sd pre/post (c/l):",
          round(sub["sd_pre"].mean() * 1000, 1),
          round(sub["sd_post"].mean() * 1000, 1))
print("sd pre range:", round(wide["sd_pre"].min() * 1000, 1),
      "-", round(wide["sd_pre"].max() * 1000, 1))
print("sd post range:", round(wide["sd_post"].min() * 1000, 1),
      "-", round(wide["sd_post"].max() * 1000, 1))
