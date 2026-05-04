# Phoveus

Scaffolded from a custom framework template.

## Structure

```
.
├── backend/    # FastAPI + Hexagonal Architecture (Python)
├── frontend/   # React + TypeScript + Vite + Tailwind CSS
└── README.md
```

See each directory's README for details:

- [Backend](backend/README.md)
- [Frontend](frontend/README.md)

## Tracking framework upstream

To pull future framework updates into this project:

```bash
git remote add framework /Users/wilmeradalid/code/maborak/framework
git fetch framework
git merge --allow-unrelated-histories framework/main
```

Resolve conflicts in the renamed brand strings and env prefix as needed.
